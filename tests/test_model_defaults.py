from __future__ import annotations

import inspect

from adproof.infrastructure.settings import Settings
from adproof.model_client import GoogleGenAIClient


def test_ollama_is_the_default_provider(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.delenv("ADPROOF_MODEL_PROVIDER", raising=False)
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("ADPROOF_WORKFLOW_DEADLINE_SECONDS", raising=False)

    settings = Settings.from_env()
    assert settings.model_provider == "ollama"
    assert settings.active_model == "qwen2.5vl:3b"
    assert settings.ollama_base_url == "http://127.0.0.1:11434"
    assert settings.workflow_deadline_seconds == 600
    assert settings.gemini_model == "gemini-3.5-flash"
    assert inspect.signature(GoogleGenAIClient).parameters["model"].default == "gemini-3.5-flash"


def test_gemini_model_remains_environment_configurable(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_MODEL", "approved-override")

    assert Settings.from_env().gemini_model == "approved-override"
