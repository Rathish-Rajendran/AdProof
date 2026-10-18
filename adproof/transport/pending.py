from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

from adproof.domain.models import TypedErrorCode
from adproof.transport.models import SpecialistOperation, SpecialistResult, SpecialistTask


class CorrelationError(ValueError):
    pass


@dataclass
class PendingTask:
    expected_sender: str
    task: SpecialistTask
    future: asyncio.Future[SpecialistResult]


class PendingTaskRegistry:
    def __init__(self) -> None:
        self._pending: dict[str, PendingTask] = {}
        self._lock = asyncio.Lock()

    async def register(
        self, task: SpecialistTask, expected_sender: str
    ) -> asyncio.Future[SpecialistResult]:
        async with self._lock:
            if task.task_id in self._pending:
                raise CorrelationError("task id is already pending")
            future: asyncio.Future[SpecialistResult] = asyncio.get_running_loop().create_future()
            self._pending[task.task_id] = PendingTask(expected_sender, task, future)
            return future

    async def accept(self, sender: str, result: SpecialistResult) -> bool:
        async with self._lock:
            pending = self._pending.get(result.task_id)
            if pending is None or pending.future.done():
                return False
            task = pending.task
            if datetime.now(UTC) >= task.deadline:
                return False
            if sender != pending.expected_sender:
                return False
            fields_match = (
                result.audit_id == task.audit_id
                and result.request_id == task.request_id
                and result.campaign_id == task.campaign_id
                and result.candidate_id == task.candidate_id
                and result.creative_version == task.creative_version
                and result.phase == task.phase
                and result.operation == task.operation
                and result.attempt == task.attempt
                and result.execution_mode == task.execution_mode
            )
            if not fields_match:
                return False
            pending.future.set_result(result)
            return True

    async def wait(
        self,
        task_id: str,
        future: asyncio.Future[SpecialistResult],
        *,
        timeout: float,
    ) -> SpecialistResult | TypedErrorCode:
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except TimeoutError:
            return TypedErrorCode.TASK_TIMEOUT
        finally:
            async with self._lock:
                self._pending.pop(task_id, None)

    async def cancel(self, task_id: str) -> None:
        async with self._lock:
            pending = self._pending.pop(task_id, None)
            if pending is not None and not pending.future.done():
                pending.future.cancel()


def same_task(
    *,
    request_id: str,
    campaign_id: str,
    candidate_id: str,
    phase: str,
    operation: SpecialistOperation,
    attempt: int,
) -> bool:
    return bool(
        request_id and campaign_id and candidate_id and phase and operation and attempt >= 0
    )
