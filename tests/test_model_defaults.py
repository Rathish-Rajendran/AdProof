from __future__ import annotations

import inspect

from adproof.infrastructure.settings import Settings
from adproof.model_client import GoogleGenAIClient


def test_gemini_is_the_default_provider(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.delenv("ADPROOF_MODEL_PROVIDER", raising=False)
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("ADPROOF_MODEL_DEFAULT", raising=False)
    monkeypatch.delenv("ADPROOF_MODEL_IMAGE_INSPECTION", raising=False)
    monkeypatch.delenv("ADPROOF_MODEL_CLAIM_EXTRACTION", raising=False)
    monkeypatch.delenv("ADPROOF_MODEL_EVIDENCE_ASSESSMENT", raising=False)
    monkeypatch.delenv("ADPROOF_MODEL_COPY_REMEDIATION", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("ADPROOF_WORKFLOW_DEADLINE_SECONDS", raising=False)

    settings = Settings.from_env()
    assert settings.model_provider == "gemini"
    assert settings.model_default == "gemini:gemini-3.5-flash"
    assert settings.active_model == "gemini-3.5-flash"
    assert settings.model_specs == {
        "image_inspection": "gemini:gemini-3.5-flash",
        "claim_extraction": "gemini:gemini-3.5-flash",
        "evidence_assessment": "gemini:gemini-3.5-flash",
        "copy_remediation": "gemini:gemini-3.5-flash",
    }
    assert settings.ollama_base_url == "http://127.0.0.1:11434"
    assert settings.workflow_deadline_seconds == 600
    assert settings.gemini_model == "gemini-3.5-flash"
    assert inspect.signature(GoogleGenAIClient).parameters["model"].default == "gemini-3.5-flash"


def test_legacy_gemini_environment_derives_default_model_spec(monkeypatch) -> None:
    monkeypatch.delenv("ADPROOF_MODEL_DEFAULT", raising=False)
    monkeypatch.setenv("ADPROOF_MODEL_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_MODEL", "approved-override")

    settings = Settings.from_env()

    assert settings.model_default == "gemini:approved-override"
    assert settings.model_provider == "gemini"


def test_legacy_ollama_environment_derives_model_spec_with_tag_colon(monkeypatch) -> None:
    monkeypatch.delenv("ADPROOF_MODEL_DEFAULT", raising=False)
    monkeypatch.setenv("ADPROOF_MODEL_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5:7b")

    assert Settings.from_env().model_default == "ollama:qwen2.5:7b"


def test_per_job_environment_specs_override_or_fall_back(monkeypatch) -> None:
    monkeypatch.setenv("ADPROOF_MODEL_DEFAULT", "ollama:qwen2.5:7b")
    monkeypatch.setenv("ADPROOF_MODEL_IMAGE_INSPECTION", "ollama:qwen2.5vl:7b")
    monkeypatch.setenv("ADPROOF_MODEL_EVIDENCE_ASSESSMENT", "gemini:gemini-3.5-flash")
    monkeypatch.delenv("ADPROOF_MODEL_CLAIM_EXTRACTION", raising=False)
    monkeypatch.delenv("ADPROOF_MODEL_COPY_REMEDIATION", raising=False)

    settings = Settings.from_env()

    assert settings.model_specs == {
        "image_inspection": "ollama:qwen2.5vl:7b",
        "claim_extraction": "ollama:qwen2.5:7b",
        "evidence_assessment": "gemini:gemini-3.5-flash",
        "copy_remediation": "ollama:qwen2.5:7b",
    }
