from datetime import UTC, datetime, timedelta

import pytest

from adproof.transport.models import (
    MAX_ENVELOPE_BYTES,
    SpecialistOperation,
    SpecialistResult,
    SpecialistTask,
    validate_result_shape,
    validate_task_size,
)
from adproof.transport.pending import PendingTaskRegistry


def task() -> SpecialistTask:
    return SpecialistTask(
        schema_version="1.0",
        audit_id="audit",
        task_id="task",
        request_id="request",
        campaign_id="campaign",
        candidate_id="candidate",
        creative_version=1,
        phase="ORIGINAL",
        operation=SpecialistOperation.VERIFY,
        attempt=1,
        deadline=datetime.now(UTC) + timedelta(seconds=5),
        execution_mode="TRANSPORT_TEST",
        payload_json="{}",
    )


def result(value: SpecialistTask) -> SpecialistResult:
    return SpecialistResult(
        schema_version="1.0",
        audit_id=value.audit_id,
        task_id=value.task_id,
        request_id=value.request_id,
        campaign_id=value.campaign_id,
        candidate_id=value.candidate_id,
        creative_version=value.creative_version,
        phase=value.phase,
        operation=value.operation,
        attempt=value.attempt,
        execution_mode=value.execution_mode,
        payload_json="{}",
    )


@pytest.mark.asyncio
async def test_result_from_separate_handler_correlates_against_sender_and_task():
    registry = PendingTaskRegistry()
    work = task()
    future = await registry.register(work, expected_sender="verifier-address")
    assert not await registry.accept("untrusted", result(work))
    assert not await registry.accept(
        "verifier-address",
        result(work).copy(update={"candidate_id": "different"}),
    )
    accepted = await registry.accept("verifier-address", result(work))
    assert accepted
    assert (await registry.wait(work.task_id, future, timeout=1)).task_id == "task"


@pytest.mark.asyncio
async def test_watchdog_resolves_timeout():
    registry = PendingTaskRegistry()
    work = task()
    future = await registry.register(work, expected_sender="verifier-address")
    timed_out = await registry.wait(work.task_id, future, timeout=0.001)
    assert timed_out.value == "TASK_TIMEOUT"
    assert not await registry.accept("verifier-address", result(work))


def test_transport_envelope_cap_and_exactly_one_response_body():
    work = task()
    validate_task_size(work)
    too_large = work.copy(update={"payload_json": "x" * MAX_ENVELOPE_BYTES})
    with pytest.raises(ValueError, match="PAYLOAD_TOO_LARGE"):
        validate_task_size(too_large)
    with pytest.raises(ValueError, match="exactly one"):
        validate_result_shape(result(work).copy(update={"error_json": "{}"}))
