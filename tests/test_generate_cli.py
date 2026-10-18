import asyncio
import json
from types import SimpleNamespace

from adproof import generate
from adproof.domain.models import TypedError, TypedErrorCode
from adproof.model_client import ModelClientError


def _json_reply(output: str) -> dict:
    output = output.rstrip("\n")
    assert output.startswith("```json\n")
    assert output.endswith("\n```")
    return json.loads(output.removeprefix("```json\n").removesuffix("\n```"))


def test_empty_prompt_returns_a_fenced_json_error(capsys):
    assert asyncio.run(generate._run("   ", offline=False)) == 0
    result = _json_reply(capsys.readouterr().out)

    assert list(result) == [
        "audit_id",
        "needs_review",
        "confidence",
        "summary",
        "ad",
        "compliance",
        "claims",
    ]
    assert result["needs_review"] is True
    assert result["confidence"] == 0
    assert result["ad"] is None
    assert len(result["compliance"]) == 1
    assert "Usage:" in result["compliance"][0]
    assert result["summary"] == f"Needs review: {result['compliance'][0]}"


def test_generator_failure_returns_a_fenced_json_error(monkeypatch, capsys):
    class FakeIndex:
        def ensure_built(self):
            return None

    async def fail_generation(*_args, **_kwargs):
        raise ModelClientError(
            TypedError(
                code=TypedErrorCode.MODEL_UNAVAILABLE,
                message="Model service unavailable.",
                retryable=True,
                details={
                    "attempt_violations": [
                        ["first deterministic violation"],
                        ["second deterministic violation"],
                    ]
                },
            )
        )

    monkeypatch.setattr(generate, "Settings", SimpleNamespace(from_env=lambda: object()))
    monkeypatch.setattr(generate, "CorpusIndex", FakeIndex)
    monkeypatch.setattr(generate, "build_model_client", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(generate, "_policies", lambda _platform: {})
    monkeypatch.setattr(generate, "run_generation_workflow", fail_generation)

    assert asyncio.run(generate._run("AeroBeat AB-01", offline=False)) == 0
    result = _json_reply(capsys.readouterr().out)

    assert list(result) == [
        "audit_id",
        "needs_review",
        "confidence",
        "summary",
        "ad",
        "compliance",
        "claims",
    ]
    assert result["needs_review"] is True
    assert result["confidence"] == 0
    assert result["ad"] is None
    assert result["summary"] == "Needs review: Model service unavailable. (2 more)"
    assert result["compliance"] == [
        "Model service unavailable.",
        "first deterministic violation",
        "second deterministic violation",
    ]
