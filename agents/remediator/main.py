from __future__ import annotations

import hashlib
import os
from collections import OrderedDict

import sentry_sdk
from uagents import Context, Model

from adproof.domain.models import RepairRequest, TypedError, TypedErrorCode
from adproof.infrastructure.budget import ModelCallBudget
from adproof.infrastructure.settings import Settings
from adproof.infrastructure.telemetry import initialize_telemetry
from adproof.model_client import ModelClientError, build_model_client
from adproof.remediator.remediator import remediate_copy
from adproof.transport.models import (
    SpecialistOperation,
    SpecialistResult,
    SpecialistTask,
    parse_payload,
    validate_task_size,
)
from agents.common import PORTS, load_identities, make_agent


class HealthResponse(Model):
    status: str


def run() -> None:
    settings = Settings.from_env()
    initialize_telemetry(settings, role="remediator")
    seeds, addresses = load_identities(settings)
    port = int(os.getenv("REMEDIATOR_PORT", PORTS["remediator"]))
    agent = make_agent(role="remediator", seed=seeds["remediator"], addresses=addresses, port=port)
    allowed_orchestrator = addresses["orchestrator"]
    replies: OrderedDict[tuple[str, str, str], tuple[str, SpecialistResult]] = OrderedDict()

    @agent.on_rest_get("/health", HealthResponse)
    async def health(ctx: Context) -> HealthResponse:
        return HealthResponse(status="ok")

    @agent.on_message(SpecialistTask, replies=SpecialistResult)
    async def handle_task(ctx: Context, sender: str, task: SpecialistTask) -> None:
        if sender != allowed_orchestrator:
            return
        digest = hashlib.sha256(task.payload_json.encode("utf-8")).hexdigest()
        key = (sender, str(ctx.session), task.task_id)
        cached = replies.get(key)
        if cached:
            if cached[0] == digest:
                await ctx.send(sender, cached[1])
            return
        if task.operation != SpecialistOperation.REPAIR:
            return
        budget = ModelCallBudget(task.model_call_grant)
        try:
            validate_task_size(task)
            request = parse_payload(task.payload_json, RepairRequest)
            if (
                request.audit_id != task.audit_id
                or request.request_id != task.request_id
                or request.campaign_id != task.campaign_id
                or request.candidate_id != task.candidate_id
            ):
                raise ValueError("task correlation fields disagree with repair payload")
            model = build_model_client(settings, budget)
            headers = task.trace_headers or {}
            transaction = sentry_sdk.continue_trace(
                headers, op="adproof.specialist", name="repair copy"
            )
            with transaction:
                with sentry_sdk.start_span(
                    op="adproof.repair", description="propose minimal repair"
                ):
                    repaired = await remediate_copy(
                        audit_id=request.audit_id,
                        candidate_id=request.candidate_id,
                        ad_copy=request.ad_copy,
                        issues=request.issues,
                        claims=request.claims,
                        evidence=request.evidence,
                        model=model,
                        deadline=request.deadline,
                    )
            result = SpecialistResult(
                schema_version="1.0",
                audit_id=task.audit_id,
                task_id=task.task_id,
                request_id=task.request_id,
                campaign_id=task.campaign_id,
                candidate_id=task.candidate_id,
                creative_version=task.creative_version,
                phase=task.phase,
                operation=task.operation,
                attempt=task.attempt,
                execution_mode=task.execution_mode,
                model_calls_used=budget.consumed,
                payload_json=repaired.model_dump_json(),
            )
        except ModelClientError as exc:
            result = _error_result(task, exc.error, budget.consumed)
        except Exception as exc:
            result = _error_result(
                task,
                TypedError(
                    code=TypedErrorCode.INTERNAL,
                    message=f"Remediator could not complete ({type(exc).__name__}).",
                ),
                budget.consumed,
            )
        replies[key] = (digest, result)
        replies.move_to_end(key)
        while len(replies) > 1000:
            replies.popitem(last=False)
        await ctx.send(sender, result)

    agent.run()


def _error_result(task: SpecialistTask, error: TypedError, used: int) -> SpecialistResult:
    return SpecialistResult(
        schema_version="1.0",
        audit_id=task.audit_id,
        task_id=task.task_id,
        request_id=task.request_id,
        campaign_id=task.campaign_id,
        candidate_id=task.candidate_id,
        creative_version=task.creative_version,
        phase=task.phase,
        operation=task.operation,
        attempt=task.attempt,
        execution_mode=task.execution_mode,
        model_calls_used=used,
        error_json=error.model_dump_json(),
    )


if __name__ == "__main__":
    run()
