from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

DEFAULT_MODEL_DEFAULT = "gemini:gemini-3.5-flash"
DEFAULT_MODEL_IMAGE_INSPECTION = "gemini:gemini-3.5-flash"
MODEL_PURPOSES = (
    "image_inspection",
    "claim_extraction",
    "evidence_assessment",
    "copy_remediation",
    "ad_generation",
)


@dataclass(frozen=True)
class ModelSpec:
    provider: str
    model: str

    @classmethod
    def parse(cls, value: str) -> ModelSpec:
        provider, separator, model = value.partition(":")
        if not separator or provider not in {"ollama", "gemini"} or not model.strip():
            raise ValueError("model specs must be '<ollama|gemini>:<model>'")
        return cls(provider=provider, model=model.strip())

    def __str__(self) -> str:
        return f"{self.provider}:{self.model}"


@dataclass(frozen=True)
class Settings:
    gemini_model: str = "gemini-3.5-flash"
    sentry_dsn: str | None = None
    sentry_environment: str = "development"
    sentry_traces_sample_rate: float = 0.0
    runtime_dir: Path = Path("runtime")
    model_provider: str | None = None
    ollama_model: str | None = None
    ollama_base_url: str = "http://127.0.0.1:11434"
    workflow_deadline_seconds: int = 600
    model_default: str | None = None
    model_image_inspection: str = DEFAULT_MODEL_IMAGE_INSPECTION
    model_claim_extraction: str | None = None
    model_evidence_assessment: str | None = None
    model_copy_remediation: str | None = None
    model_ad_generation: str | None = None

    _PURPOSE_FIELDS: ClassVar[dict[str, str]] = {
        "image_inspection": "model_image_inspection",
        "claim_extraction": "model_claim_extraction",
        "evidence_assessment": "model_evidence_assessment",
        "copy_remediation": "model_copy_remediation",
        "ad_generation": "model_ad_generation",
    }

    def __post_init__(self) -> None:
        if self.model_default is None:
            provider = self.model_provider or ModelSpec.parse(DEFAULT_MODEL_DEFAULT).provider
            if provider not in {"ollama", "gemini"}:
                raise ValueError("model provider must be 'ollama' or 'gemini'")
            model = self.ollama_model or "qwen2.5:3b" if provider == "ollama" else self.gemini_model
            object.__setattr__(self, "model_default", f"{provider}:{model}")

        default_spec = ModelSpec.parse(self.model_default or "")
        object.__setattr__(self, "model_default", str(default_spec))
        object.__setattr__(self, "model_provider", default_spec.provider)
        if default_spec.provider == "ollama":
            object.__setattr__(self, "ollama_model", default_spec.model)
        elif default_spec.provider == "gemini":
            object.__setattr__(self, "gemini_model", default_spec.model)

        for purpose in MODEL_PURPOSES:
            field = self._PURPOSE_FIELDS[purpose]
            override = getattr(self, field)
            if override is not None:
                object.__setattr__(self, field, str(ModelSpec.parse(override)))

    def model_spec_for(self, purpose: str) -> str:
        field = self._PURPOSE_FIELDS.get(purpose)
        override = getattr(self, field) if field else None
        return override or self.model_default or DEFAULT_MODEL_DEFAULT

    @property
    def model_specs(self) -> dict[str, str]:
        return {purpose: self.model_spec_for(purpose) for purpose in MODEL_PURPOSES}

    @property
    def active_model(self) -> str:
        return ModelSpec.parse(self.model_default or DEFAULT_MODEL_DEFAULT).model

    @classmethod
    def from_env(cls) -> Settings:
        model_default = os.getenv("ADPROOF_MODEL_DEFAULT")
        if model_default is None:
            provider = os.getenv(
                "ADPROOF_MODEL_PROVIDER", ModelSpec.parse(DEFAULT_MODEL_DEFAULT).provider
            )
            if provider not in {"ollama", "gemini"}:
                raise ValueError("ADPROOF_MODEL_PROVIDER must be 'ollama' or 'gemini'")
            legacy_model = (
                os.getenv("OLLAMA_MODEL") or "qwen2.5:3b"
                if provider == "ollama"
                else os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
            )
            model_default = f"{provider}:{legacy_model}"

        return cls(
            model_default=model_default,
            model_image_inspection=(
                os.getenv("ADPROOF_MODEL_IMAGE_INSPECTION") or DEFAULT_MODEL_IMAGE_INSPECTION
            ),
            model_claim_extraction=os.getenv("ADPROOF_MODEL_CLAIM_EXTRACTION") or None,
            model_evidence_assessment=os.getenv("ADPROOF_MODEL_EVIDENCE_ASSESSMENT") or None,
            model_copy_remediation=os.getenv("ADPROOF_MODEL_COPY_REMEDIATION") or None,
            model_ad_generation=os.getenv("ADPROOF_MODEL_AD_GENERATION") or None,
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash"),
            ollama_model=os.getenv("OLLAMA_MODEL") or None,
            ollama_base_url=os.getenv("OLLAMA_BASE_URL") or "http://127.0.0.1:11434",
            workflow_deadline_seconds=int(os.getenv("ADPROOF_WORKFLOW_DEADLINE_SECONDS", "600")),
            sentry_dsn=os.getenv("SENTRY_DSN") or None,
            sentry_environment=os.getenv("SENTRY_ENVIRONMENT", "development"),
            sentry_traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0")),
            runtime_dir=Path(os.getenv("ADPROOF_RUNTIME_DIR", "runtime")),
        )


def load_or_create_seeds(runtime_dir: Path, supplied: dict[str, str | None]) -> dict[str, str]:
    runtime_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    runtime_dir.chmod(0o700)
    seed_path = runtime_dir / "agent-seeds.json"
    existing: dict[str, str] = {}
    if seed_path.exists():
        existing = json.loads(seed_path.read_text(encoding="utf-8"))
    seeds = {
        role: supplied.get(role) or existing.get(role) or secrets.token_urlsafe(32)
        for role in ("orchestrator", "verifier", "remediator", "generator")
    }
    seed_path.write_text(json.dumps(seeds, sort_keys=True), encoding="utf-8")
    seed_path.chmod(0o600)
    return seeds


def write_public_addresses(runtime_dir: Path, addresses: dict[str, str]) -> Path:
    runtime_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = runtime_dir / "agents.json"
    path.write_text(json.dumps(addresses, indent=2, sort_keys=True), encoding="utf-8")
    path.chmod(0o644)
    return path
