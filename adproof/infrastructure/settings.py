from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    gemini_model: str = "gemini-3.5-flash"
    sentry_dsn: str | None = None
    sentry_environment: str = "development"
    sentry_traces_sample_rate: float = 0.0
    runtime_dir: Path = Path("runtime")

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash"),
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
        for role in ("orchestrator", "verifier", "remediator")
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
