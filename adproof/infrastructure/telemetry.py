from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any

import sentry_sdk

from adproof.infrastructure.settings import Settings

_SECRET_PATTERN = re.compile(
    r"(?i)(api[_-]?key|authorization|token|password|secret|dsn)\s*[:=]\s*[^&\s]+"
)


def _scrub(value: Any) -> Any:
    if isinstance(value, str):
        return _SECRET_PATTERN.sub(r"\1=[REDACTED]", value)[:2048]
    if isinstance(value, Mapping):
        return {
            key: "[REDACTED]"
            if re.search(r"(?i)(copy|prompt|body|image|authorization|token|secret|email)", str(key))
            else _scrub(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_scrub(item) for item in value[:100]]
    return value


def _before_send(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any]:
    return _scrub(event)


def _before_send_log(log: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any]:
    return _scrub(log)


def initialize_telemetry(settings: Settings, *, role: str) -> bool:
    if not settings.sentry_dsn:
        return False
    try:
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.sentry_environment,
            traces_sample_rate=settings.sentry_traces_sample_rate,
            enable_logs=True,
            send_default_pii=False,
            before_send=_before_send,
            before_send_log=_before_send_log,
        )
        sentry_sdk.set_tag("service_role", role)
        return True
    except Exception:
        logging.getLogger(__name__).warning("telemetry initialization unavailable")
        return False


def record_event(
    event: str,
    *,
    audit_id: str | None = None,
    role: str,
    stage: str | None = None,
    duration: float | None = None,
    result: str | None = None,
    execution_mode: str | None = None,
) -> None:
    safe = {
        key: value
        for key, value in {
            "audit_id": audit_id,
            "role": role,
            "stage": stage,
            "duration": duration,
            "result": result,
            "execution_mode": execution_mode,
        }.items()
        if value is not None
    }
    try:
        sentry_sdk.logger.info(event, **safe)
    except Exception:
        logging.getLogger(__name__).debug("telemetry event dropped")
