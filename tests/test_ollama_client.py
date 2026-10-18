from __future__ import annotations

import asyncio
import base64
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import BaseModel

import adproof.model_client as model_module
from adproof.domain.models import TypedErrorCode
from adproof.infrastructure.budget import ModelCallBudget
from adproof.infrastructure.settings import Settings
from adproof.model_client import (
    ModelClientError,
    OllamaClient,
    RoutingModelClient,
    build_model_client,
)


class _Output(BaseModel):
    ok: bool


def _deadline() -> datetime:
    return datetime.now(UTC) + timedelta(seconds=10)


def _response(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "qwen2.5vl:3b",
            "message": {"content": content},
            "prompt_eval_count": 11,
            "eval_count": 7,
        },
    )


@pytest.mark.asyncio
async def test_ollama_joins_prompt_encodes_images_and_validates_schema() -> None:
    captured: dict[str, object] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return _response('{"ok": true}')

    model = OllamaClient(transport=httpx.MockTransport(handle))
    image = b"\x89PNG\r\nsynthetic"
    result = await model.generate_json(
        ["first instruction", (image, "image/png"), "second instruction"],
        _Output,
        deadline=_deadline(),
        purpose="unit_test",
    )

    assert result.data == _Output(ok=True)
    assert result.model_version == "qwen2.5vl:3b"
    assert result.usage == {"prompt_tokens": 11, "candidate_tokens": 7}
    assert captured["model"] == "qwen2.5vl:3b"
    assert captured["messages"] == [
        {
            "role": "user",
            "content": "first instruction\n\nsecond instruction",
            "images": [base64.b64encode(image).decode("ascii")],
        }
    ]
    assert captured["format"] == _Output.model_json_schema()
    assert captured["stream"] is False
    assert captured["options"] == {"temperature": 0}
    assert model.call_records[0]["reported_model_version"] == "qwen2.5vl:3b"


@pytest.mark.asyncio
async def test_ollama_corrects_malformed_json_once_and_accounts_for_both_calls() -> None:
    prompts: list[str] = []
    responses = iter((_response("not json"), _response('{"ok": true}')))

    def handle(request: httpx.Request) -> httpx.Response:
        prompts.append(json.loads(request.content)["messages"][0]["content"])
        return next(responses)

    budget = ModelCallBudget(2)
    model = OllamaClient(budget=budget, transport=httpx.MockTransport(handle))
    result = await model.generate_json(
        ["return JSON"],
        _Output,
        deadline=_deadline(),
        purpose="correct_json",
    )

    assert result.data.ok is True
    assert prompts[0] == "return JSON"
    assert "previous response did not validate" in prompts[1]
    assert budget.consumed == 2
    assert [record.get("error") for record in model.call_records] == [
        TypedErrorCode.MODEL_MALFORMED_OUTPUT.value,
        None,
    ]


@pytest.mark.asyncio
async def test_ollama_malformed_json_after_correction_is_typed() -> None:
    def handle(_request: httpx.Request) -> httpx.Response:
        return _response('{"ok": "not-a-boolean"}')

    model = OllamaClient(transport=httpx.MockTransport(handle))
    with pytest.raises(ModelClientError) as error:
        await model.generate_json(
            ["return JSON"],
            _Output,
            deadline=_deadline(),
            purpose="bad_json",
        )

    assert error.value.error.code == TypedErrorCode.MODEL_MALFORMED_OUTPUT
    assert len(model.call_records) == 2


@pytest.mark.asyncio
async def test_ollama_connection_error_retries_once_and_is_retryable(monkeypatch) -> None:
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("connection refused", request=request)

    monkeypatch.setattr(model_module.random, "uniform", lambda _low, _high: 0.0)
    model = OllamaClient(transport=httpx.MockTransport(handle))
    with pytest.raises(ModelClientError) as error:
        await model.generate_json(
            ["return JSON"],
            _Output,
            deadline=_deadline(),
            purpose="connection_error",
        )

    assert calls == 2
    assert error.value.error.code == TypedErrorCode.MODEL_UNAVAILABLE
    assert error.value.error.retryable is True


@pytest.mark.asyncio
async def test_ollama_server_error_retries_once_and_is_retryable(monkeypatch) -> None:
    calls = 0

    def handle(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, json={"error": "unavailable"})

    monkeypatch.setattr(model_module.random, "uniform", lambda _low, _high: 0.0)
    model = OllamaClient(transport=httpx.MockTransport(handle))
    with pytest.raises(ModelClientError) as error:
        await model.generate_json(
            ["return JSON"],
            _Output,
            deadline=_deadline(),
            purpose="server_error",
        )

    assert calls == 2
    assert error.value.error.code == TypedErrorCode.MODEL_UNAVAILABLE
    assert error.value.error.retryable is True


@pytest.mark.asyncio
async def test_ollama_deadline_maps_to_timeout() -> None:
    class SlowTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, _request: httpx.Request) -> httpx.Response:
            await asyncio.sleep(1)
            return _response('{"ok": true}')

    model = OllamaClient(transport=SlowTransport())
    with pytest.raises(ModelClientError) as error:
        await model.generate_json(
            ["return JSON"],
            _Output,
            deadline=datetime.now(UTC) + timedelta(milliseconds=20),
            purpose="deadline",
        )

    assert error.value.error.code == TypedErrorCode.TIMEOUT


@pytest.mark.asyncio
async def test_ollama_404_reports_model_not_pulled_without_retry() -> None:
    calls = 0

    def handle(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(404, json={"error": "model not found"})

    model = OllamaClient(
        model="missing-model",
        transport=httpx.MockTransport(handle),
    )
    with pytest.raises(ModelClientError) as error:
        await model.generate_json(
            ["return JSON"],
            _Output,
            deadline=_deadline(),
            purpose="missing_model",
        )

    assert calls == 1
    assert error.value.error.code == TypedErrorCode.MODEL_UNAVAILABLE
    assert error.value.error.retryable is False
    assert error.value.error.message == "Ollama model missing-model is not pulled"


def test_model_client_factory_returns_lazy_router() -> None:
    budget = ModelCallBudget(3)

    ollama = build_model_client(Settings(), budget)

    assert isinstance(ollama, RoutingModelClient)
    assert ollama.budget is budget
    assert ollama._clients == {}


@pytest.mark.asyncio
async def test_gemini_spec_without_key_fails_only_when_job_is_called(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    model = build_model_client(
        Settings(
            model_default="ollama:qwen2.5:7b",
            model_evidence_assessment="gemini:gemini-3.5-flash",
        )
    )

    assert isinstance(model, RoutingModelClient)
    assert model._clients == {}

    with pytest.raises(ModelClientError) as error:
        await model.generate_json(
            ["return JSON"],
            _Output,
            deadline=_deadline(),
            purpose="evidence_assessment",
        )

    assert error.value.error.code == TypedErrorCode.MODEL_AUTH
    assert model._clients == {}


def test_invalid_model_provider_raises_value_error(monkeypatch) -> None:
    monkeypatch.delenv("ADPROOF_MODEL_DEFAULT", raising=False)
    monkeypatch.setenv("ADPROOF_MODEL_PROVIDER", "unknown")

    with pytest.raises(ValueError, match="ADPROOF_MODEL_PROVIDER"):
        Settings.from_env()
