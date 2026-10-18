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

    assert result["request"] == {
        "prompt": "",
        "platform": "google_ads",
        "jurisdiction": "US",
        "language": "en",
        "audience": "adults",
    }
    assert list(result) == [
        "audit_id",
        "verdict",
        "confidence",
        "summary",
        "request",
        "original_check",
        "final",
        "claims",
        "compliance",
        "checks_failed",
        "notes",
    ]
    assert result["verdict"] == "NEEDS_HUMAN_APPROVAL"
    assert result["confidence"] == 0
    assert result["final"] == {
        "decision": "HUMAN_REVIEW",
        "ad_copy": None,
        "repair_verified": False,
    }
    assert "Usage:" in result["notes"][0]


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

    assert result["request"] == {
        "prompt": "AeroBeat AB-01",
        "platform": "google_ads",
        "jurisdiction": "US",
        "language": "en",
        "audience": "adults",
    }
    assert list(result) == [
        "audit_id",
        "verdict",
        "confidence",
        "summary",
        "request",
        "original_check",
        "final",
        "claims",
        "compliance",
        "checks_failed",
        "notes",
    ]
    assert result["summary"] == (
        "1 of 1 checks failed (verification: Model service unavailable.). Human approval needed."
    )
    assert result["final"]["decision"] == "HUMAN_REVIEW"
    assert result["final"]["ad_copy"] is None
    assert result["final"]["repair_verified"] is False
    assert result["checks_failed"] == [
        {"check": "verification", "reason": "Model service unavailable."}
    ]
    assert result["notes"] == [
        "Model service unavailable.",
        "Attempt 1: first deterministic violation",
        "Attempt 2: second deterministic violation",
    ]
