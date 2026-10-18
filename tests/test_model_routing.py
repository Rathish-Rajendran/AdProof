from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import BaseModel

import adproof.model_client as model_module
from adproof.infrastructure.budget import ModelCallBudget
from adproof.infrastructure.settings import ModelSpec, Settings
from adproof.model_client import ModelResponse, RoutingModelClient, build_model_client


class _Output(BaseModel):
    purpose: str


def _deadline() -> datetime:
    return datetime.now(UTC) + timedelta(seconds=10)


def test_model_spec_splits_only_at_the_first_colon() -> None:
    spec = ModelSpec.parse("ollama:qwen2.5:7b")

    assert spec.provider == "ollama"
    assert spec.model == "qwen2.5:7b"
    assert str(spec) == "ollama:qwen2.5:7b"


@pytest.mark.parametrize("value", ["unknown:model", "ollama:", "gemini:   ", "qwen2.5:7b"])
def test_model_spec_rejects_invalid_provider_or_empty_model(value: str) -> None:
    with pytest.raises(ValueError):
        ModelSpec.parse(value)


def test_settings_rejects_invalid_model_specs() -> None:
    with pytest.raises(ValueError):
        Settings(model_default="unknown:model")
    with pytest.raises(ValueError):
        Settings(model_default="ollama:")


class _StubClient:
    def __init__(
        self,
        *,
        provider: str,
        model: str,
        budget: ModelCallBudget | None,
        record_callback,
        **_kwargs: Any,
    ):
        self.provider = provider
        self.model = model
        self.budget = budget
        self.record_callback = record_callback

    async def generate_json(
        self,
        prompt_parts,
        schema,
        *,
        deadline,
        purpose: str,
    ) -> ModelResponse:
        record = {
            "purpose": purpose,
            "model": self.model,
            "reported_model_version": self.model,
            "usage": {},
        }
        self.record_callback(record)
        return ModelResponse(
            data=schema(purpose=purpose),
            model_version=self.model,
            usage={},
            latency=0.0,
        )


@pytest.mark.asyncio
async def test_router_routes_jobs_falls_back_and_aggregates_records(monkeypatch) -> None:
    constructed: list[dict[str, Any]] = []

    def make_client(provider: str):
        def factory(**kwargs):
            constructed.append({"provider": provider, **kwargs})
            return _StubClient(provider=provider, **kwargs)

        return factory

    monkeypatch.setattr(model_module, "OllamaClient", make_client("ollama"))
    monkeypatch.setattr(model_module, "GoogleGenAIClient", make_client("gemini"))
    budget = ModelCallBudget(8)
    settings = Settings(
        model_default="ollama:qwen2.5:7b",
        model_image_inspection="ollama:qwen2.5vl:7b",
        model_claim_extraction="gemini:gemini-3.5-flash",
        model_copy_remediation="gemini:gemini-3.5-flash",
    )
    model = build_model_client(settings, budget)
    assert isinstance(model, RoutingModelClient)

    purposes = (
        "image_inspection",
        "claim_extraction",
        "evidence_assessment",
        "copy_remediation",
        "unknown_job",
    )
    for purpose in purposes:
        result = await model.generate_json(
            ["return JSON"],
            _Output,
            deadline=_deadline(),
            purpose=purpose,
        )
        assert result.data.purpose == purpose

    assert [(client["provider"], client["model"]) for client in constructed] == [
        ("ollama", "qwen2.5vl:7b"),
        ("gemini", "gemini-3.5-flash"),
        ("ollama", "qwen2.5:7b"),
    ]
    assert all(client["budget"] is budget for client in constructed)
    assert [record["purpose"] for record in model.call_records] == list(purposes)
    assert [record["provider"] for record in model.call_records] == [
        "ollama",
        "gemini",
        "ollama",
        "gemini",
        "ollama",
    ]
    assert [record["model_spec"] for record in model.call_records] == [
        "ollama:qwen2.5vl:7b",
        "gemini:gemini-3.5-flash",
        "ollama:qwen2.5:7b",
        "gemini:gemini-3.5-flash",
        "ollama:qwen2.5:7b",
    ]


def test_job_overrides_fall_back_to_the_default_spec() -> None:
    settings = Settings(model_default="ollama:qwen2.5:3b")

    assert settings.model_spec_for("claim_extraction") == "ollama:qwen2.5:3b"
    assert settings.model_spec_for("evidence_assessment") == "ollama:qwen2.5:3b"
    assert settings.model_spec_for("copy_remediation") == "ollama:qwen2.5:3b"
    assert settings.model_spec_for("not_a_job") == "ollama:qwen2.5:3b"
