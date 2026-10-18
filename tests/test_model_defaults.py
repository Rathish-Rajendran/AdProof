from __future__ import annotations

import inspect

from adproof.infrastructure.settings import Settings
from adproof.model_client import GoogleGenAIClient


def test_approved_gemini_model_is_the_default(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_MODEL", raising=False)

    assert Settings.from_env().gemini_model == "gemini-3.5-flash"
    assert inspect.signature(GoogleGenAIClient).parameters["model"].default == "gemini-3.5-flash"


def test_gemini_model_remains_environment_configurable(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_MODEL", "approved-override")

    assert Settings.from_env().gemini_model == "approved-override"
