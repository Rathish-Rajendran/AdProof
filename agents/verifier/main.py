from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections import OrderedDict

import sentry_sdk
from uagents import Context, Model

from adproof.domain.models import (
    TypedError,
    TypedErrorCode,
    VerificationRequest,
)
from adproof.infrastructure.budget import ModelCallBudget
from adproof.infrastructure.safe_http import SafeHttpClient
from adproof.infrastructure.settings import Settings
from adproof.infrastructure.telemetry import initialize_telemetry
from adproof.model_client import ModelClientError, build_model_client
from adproof.transport.models import (
    SpecialistOperation,
    SpecialistResult,
    SpecialistTask,
    parse_payload,
    validate_task_size,
)
from adproof.verifier.policy import PolicyEngine
from adproof.verifier.verifier import VerificationDependencies, verify_campaign
from agents.common import PORTS, load_identities, make_agent, repository_root


class HealthResponse(Model):
    status: str


def run() -> None:
    settings = Settings.from_env()
    initialize_telemetry(settings, role="verifier")
    seeds, addresses = load_identities(settings)
    port = int(os.getenv("VERIFIER_PORT", PORTS["verifier"]))
    agent = make_agent(role="verifier", seed=seeds["verifier"], addresses=addresses, port=port)
    allowed_orchestrator = addresses["orchestrator"]
    root = repository_root()
    policy = PolicyEngine.from_files(
        root / "data/policies/catalog.json",
        root / "data/policies/packs/google_ads_us_electronics_v1.json",
    )
    http = SafeHttpClient()
    replies: OrderedDict[tuple[str, str, str], tuple[str, SpecialistResult]] = OrderedDict()

    @agent.on_rest_get("/health", HealthResponse)
    async def health(ctx: Context) -> HealthResponse:
        return HealthResponse(status="ok")

    @agent.on_event("shutdown")
    async def shutdown(ctx: Context) -> None:
        await http.close()

    @agent.on_message(SpecialistTask, replies=SpecialistResult)
    async def handle_task(ctx: Context, sender: str, task: SpecialistTask) -> None:
        if sender != allowed_orchestrator:
            return
        if task.execution_mode == "TRANSPORT_TEST" and os.getenv("ADPROOF_TRANSPORT_PROBE") == "1":
            validate_task_size(task)
            probe = json.loads(task.payload_json).get("probe")
            if probe == "timeout":
                return
            if probe == "delayed":
                await asyncio.sleep(0.15)
                await ctx.send(
                    sender,
                    SpecialistResult(
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
                        payload_json='{"probe":"delayed-result"}',
                    ),
                )
            return
        digest = hashlib.sha256(task.payload_json.encode("utf-8")).hexdigest()
        key = (sender, str(ctx.session), task.task_id)
        cached = replies.get(key)
        if cached:
            if cached[0] == digest:
                await ctx.send(sender, cached[1])
            return
        if task.operation != SpecialistOperation.VERIFY:
            return
        result: SpecialistResult
        budget = ModelCallBudget(task.model_call_grant)
        try:
            validate_task_size(task)
            request = parse_payload(task.payload_json, VerificationRequest)
            if (
                request.audit_id != task.audit_id
                or request.request_id != task.request_id
                or request.campaign_id != task.campaign_id
                or request.candidate_id != task.candidate_id
                or request.creative_version != task.creative_version
                or request.phase.value != task.phase
                or request.deadline != task.deadline
            ):
                raise ValueError("task correlation fields disagree with verification payload")
            model = build_model_client(settings, budget)
            dependencies = VerificationDependencies(http=http, model=model, policy=policy)
            headers = task.trace_headers or {}
            transaction = sentry_sdk.continue_trace(
                headers, op="adproof.specialist", name="verify campaign"
            )
            with transaction:
                with sentry_sdk.start_span(op="adproof.verify", description="verify candidate"):
                    verified = await verify_campaign(request, dependencies)
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
                payload_json=verified.model_dump_json(),
            )
        except ModelClientError as exc:
            result = _error_result(task, exc.error, budget.consumed)
        except Exception as exc:
            result = _error_result(
                task,
                TypedError(
                    code=TypedErrorCode.INTERNAL,
                    message=f"Verifier could not complete ({type(exc).__name__}).",
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
