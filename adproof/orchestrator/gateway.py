from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime
from typing import Any

import sentry_sdk
from pydantic import BaseModel, ValidationError
from uagents import Context

from adproof.domain.models import (
    RepairRequest,
    RepairResult,
    TypedError,
    TypedErrorCode,
    VerificationRequest,
    VerificationResult,
)
from adproof.infrastructure.budget import BudgetExhausted, ModelCallBudget
from adproof.infrastructure.telemetry import record_event
from adproof.transport.models import (
    SpecialistOperation,
    SpecialistTask,
    parse_payload,
    validate_result_shape,
    validate_task_size,
)
from adproof.transport.pending import PendingTaskRegistry


def trace_headers() -> dict[str, str] | None:
    try:
        headers = {
            "sentry-trace": sentry_sdk.get_traceparent(),
            "baggage": sentry_sdk.get_baggage(),
        }
        present = {key: value for key, value in headers.items() if value}
        return present or None
    except Exception:
        return None


class LocalGateway:
    def __init__(self, verification_dependencies: Any, model: Any):
        self.verification_dependencies = verification_dependencies
        self.model = model

    async def verify(self, request: VerificationRequest) -> VerificationResult:
        from adproof.verifier.verifier import verify_campaign

        for attempt in (1, 2):
            result = await verify_campaign(request, self.verification_dependencies)
            error = _retryable_error(result)
            if attempt == 2 or error is None or datetime.now(UTC) >= request.deadline:
                return result
            record_event(
                "retry_scheduled",
                audit_id=request.audit_id,
                role="local_gateway",
                stage="verify",
                result=error.code.value,
            )
        return result

    async def repair(self, request: RepairRequest) -> RepairResult:
        from adproof.remediator.remediator import remediate_copy

        for attempt in (1, 2):
            result = await remediate_copy(
                audit_id=request.audit_id,
                candidate_id=request.candidate_id,
                ad_copy=request.ad_copy,
                issues=request.issues,
                claims=request.claims,
                evidence=request.evidence,
                model=self.model,
                deadline=request.deadline,
            )
            error = _retryable_error(result)
            if attempt == 2 or error is None or datetime.now(UTC) >= request.deadline:
                return result
            record_event(
                "retry_scheduled",
                audit_id=request.audit_id,
                role="local_gateway",
                stage="repair",
                result=error.code.value,
            )
        return result


class UAgentsGateway:
    def __init__(
        self,
        *,
        context: Context,
        pending: PendingTaskRegistry,
        verifier_address: str,
        remediator_address: str,
        budget: ModelCallBudget,
        execution_mode: str,
    ):
        self.context = context
        self.pending = pending
        self.addresses = {
            SpecialistOperation.VERIFY: verifier_address,
            SpecialistOperation.REPAIR: remediator_address,
        }
        self.budget = budget
        self.execution_mode = execution_mode

    async def verify(self, request: VerificationRequest) -> VerificationResult | TypedError:
        return await self._dispatch(
            operation=SpecialistOperation.VERIFY,
            request=request,
            response_model=VerificationResult,
            audit_id=request.audit_id,
            campaign_id=request.campaign_id,
            candidate_id=request.candidate_id,
            creative_version=request.creative_version,
            phase=request.phase.value,
            deadline=request.deadline,
        )

    async def repair(self, request: RepairRequest) -> RepairResult | TypedError:
        return await self._dispatch(
            operation=SpecialistOperation.REPAIR,
            request=request,
            response_model=RepairResult,
            audit_id=request.audit_id,
            campaign_id=request.campaign_id,
            candidate_id=request.candidate_id,
            creative_version=1,
            phase="REPAIR",
            deadline=request.deadline,
        )

    async def _dispatch(
        self,
        *,
        operation: SpecialistOperation,
        request: BaseModel,
        response_model: type[BaseModel],
        audit_id: str,
        campaign_id: str,
        candidate_id: str,
        creative_version: int,
        phase: str,
        deadline: datetime,
    ) -> Any | TypedError:
        for attempt in (1, 2):
            response = await self._dispatch_attempt(
                operation=operation,
                request=request,
                response_model=response_model,
                audit_id=audit_id,
                campaign_id=campaign_id,
                candidate_id=candidate_id,
                creative_version=creative_version,
                phase=phase,
                deadline=deadline,
                attempt=attempt,
            )
            error = _retryable_error(response)
            remaining = (deadline - datetime.now(UTC)).total_seconds()
            if attempt == 2 or error is None or remaining <= 0:
                return response
            record_event(
                "retry_scheduled",
                audit_id=audit_id,
                role="orchestrator",
                stage=operation.value.lower(),
                result=error.code.value,
            )
        return response

    async def _dispatch_attempt(
        self,
        *,
        operation: SpecialistOperation,
        request: BaseModel,
        response_model: type[BaseModel],
        audit_id: str,
        campaign_id: str,
        candidate_id: str,
        creative_version: int,
        phase: str,
        deadline: datetime,
        attempt: int,
    ) -> Any | TypedError:
        remaining = (deadline - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            return TypedError(code=TypedErrorCode.TASK_TIMEOUT, message="No dispatch time remains.")
        grant = await self.budget.grant(8)
        if not grant:
            return TypedError(
                code=TypedErrorCode.BUDGET_EXHAUSTED, message="No model-call grant remains."
            )
        try:
            await self.budget.reserve(grant)
        except BudgetExhausted:
            return TypedError(
                code=TypedErrorCode.BUDGET_EXHAUSTED, message="Model-call budget exhausted."
            )
        task_id = uuid.uuid4().hex
        task = SpecialistTask(
            schema_version="1.0",
            audit_id=audit_id,
            task_id=task_id,
            request_id=getattr(request, "request_id", task_id),
            campaign_id=campaign_id,
            candidate_id=candidate_id,
            creative_version=creative_version,
            phase=phase,
            operation=operation,
            attempt=attempt,
            deadline=deadline,
            execution_mode=self.execution_mode,
            payload_json=request.model_dump_json(),
            model_call_grant=grant,
            trace_headers=trace_headers(),
        )
        try:
            validate_task_size(task)
            future = await self.pending.register(task, self.addresses[operation])
        except (ValueError, RuntimeError) as exc:
            await self.budget.release(grant)
            code = (
                TypedErrorCode.PAYLOAD_TOO_LARGE
                if "PAYLOAD_TOO_LARGE" in str(exc)
                else TypedErrorCode.INTERNAL
            )
            return TypedError(code=code, message="Specialist task could not be registered.")
        try:
            status = await self.context.send(
                self.addresses[operation],
                task,
                timeout=max(1, math.ceil(remaining)),
            )
            if getattr(getattr(status, "status", None), "value", None) == "failed":
                await self.pending.cancel(task_id)
                await self.budget.release(grant)
                return TypedError(
                    code=TypedErrorCode.SOURCE_UNAVAILABLE,
                    message="Specialist task delivery failed.",
                    retryable=True,
                )
            response = await self.pending.wait(task_id, future, timeout=remaining)
        except TimeoutError:
            await self.pending.cancel(task_id)
            await self.budget.release(grant)
            return TypedError(
                code=TypedErrorCode.TASK_TIMEOUT,
                message="Specialist dispatch timed out.",
                retryable=True,
            )
        except Exception:
            await self.pending.cancel(task_id)
            await self.budget.release(grant)
            return TypedError(code=TypedErrorCode.INTERNAL, message="Specialist dispatch failed.")
        if isinstance(response, TypedErrorCode):
            await self.budget.release(grant)
            record_event(
                "task_timed_out",
                audit_id=audit_id,
                role="orchestrator",
                stage=operation.value.lower(),
                result=response.value,
            )
            return TypedError(code=response, message="Specialist task timed out.", retryable=True)
        try:
            validate_result_shape(response)
            used = min(max(response.model_calls_used, 0), grant)
            if used:
                await self.budget.consume(used)
            await self.budget.release(grant - used)
            if response.error_json is not None:
                return TypedError.model_validate_json(response.error_json)
            return parse_payload(response.payload_json or "", response_model)
        except (ValidationError, ValueError, TypeError) as exc:
            code = (
                TypedErrorCode.PAYLOAD_TOO_LARGE
                if "PAYLOAD_TOO_LARGE" in str(exc)
                else TypedErrorCode.MODEL_MALFORMED_OUTPUT
            )
            return TypedError(
                code=code,
                message=f"Specialist returned an invalid payload ({type(exc).__name__}).",
            )


def _retryable_error(result: Any) -> TypedError | None:
    retryable_codes = {TypedErrorCode.TASK_TIMEOUT, TypedErrorCode.MODEL_UNAVAILABLE}
    if isinstance(result, TypedError):
        return result if result.code in retryable_codes and result.retryable else None
    for error in getattr(result, "errors", []):
        if error.code in retryable_codes and error.retryable:
            return error
    return None
