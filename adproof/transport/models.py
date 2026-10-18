from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from typing import Any

from uagents import Model

MAX_ENVELOPE_BYTES = 32 * 1024


class SpecialistOperation(StrEnum):
    VERIFY = "VERIFY"
    REPAIR = "REPAIR"
    GENERATE = "GENERATE"


class SpecialistTask(Model):
    schema_version: str
    audit_id: str
    task_id: str
    request_id: str
    campaign_id: str
    candidate_id: str
    creative_version: int
    phase: str
    operation: SpecialistOperation
    attempt: int
    deadline: datetime
    execution_mode: str
    payload_json: str
    model_call_grant: int = 0
    trace_headers: dict[str, str] | None = None


class SpecialistResult(Model):
    schema_version: str
    audit_id: str
    task_id: str
    request_id: str
    campaign_id: str
    candidate_id: str
    creative_version: int
    phase: str
    operation: SpecialistOperation
    attempt: int
    execution_mode: str
    model_calls_used: int = 0
    payload_json: str | None = None
    error_json: str | None = None
    trace_headers: dict[str, str] | None = None


def validate_task_size(task: SpecialistTask) -> None:
    encoded = json.dumps(task.dict(), default=str, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_ENVELOPE_BYTES:
        raise ValueError("PAYLOAD_TOO_LARGE")
    if len(task.payload_json.encode("utf-8")) > MAX_ENVELOPE_BYTES:
        raise ValueError("PAYLOAD_TOO_LARGE")


def validate_result_shape(result: SpecialistResult) -> None:
    if (result.payload_json is None) == (result.error_json is None):
        raise ValueError(
            "specialist response must contain exactly one success payload or typed error"
        )
    encoded = json.dumps(result.dict(), default=str, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_ENVELOPE_BYTES:
        raise ValueError("PAYLOAD_TOO_LARGE")


def parse_payload(payload_json: str, model: type[Any]) -> Any:
    return model.model_validate_json(payload_json)
