from __future__ import annotations

import hashlib
import json
import os
from collections import OrderedDict

from uagents import Context, Model

from adproof.domain.models import TypedError, TypedErrorCode
from adproof.generator.generator import GenerationTask, generate_ad
from adproof.infrastructure.budget import ModelCallBudget
from adproof.infrastructure.settings import Settings
from adproof.infrastructure.telemetry import initialize_telemetry
from adproof.model_client import ModelClientError, build_model_client
from adproof.rag.index import CorpusIndex
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
    initialize_telemetry(settings, role="generator")
    seeds, addresses = load_identities(settings)
    agent = make_agent(
        role="generator",
        seed=seeds["generator"],
        addresses=addresses,
        port=int(os.getenv("GENERATOR_PORT", PORTS["generator"])),
    )
    index = CorpusIndex()
    replies: OrderedDict[tuple[str, str, str], tuple[str, SpecialistResult]] = OrderedDict()

    @agent.on_rest_get("/health", HealthResponse)
    async def health(ctx: Context) -> HealthResponse:
        return HealthResponse(status="ok")

    @agent.on_message(SpecialistTask, replies=SpecialistResult)
    async def handle_task(ctx: Context, sender: str, task: SpecialistTask) -> None:
        if sender != addresses["orchestrator"] or task.operation != SpecialistOperation.GENERATE:
            return
        digest = hashlib.sha256(task.payload_json.encode("utf-8")).hexdigest()
        key = (sender, str(ctx.session), task.task_id)
        cached = replies.get(key)
        if cached:
            if cached[0] == digest:
                await ctx.send(sender, cached[1])
            return
        try:
            validate_task_size(task)
            request = parse_payload(task.payload_json, GenerationTask)
            if (
                request.audit_id != task.audit_id
                or request.request_id != task.request_id
                or request.campaign_id != task.campaign_id
                or request.candidate_id != task.candidate_id
                or request.creative_version != task.creative_version
                or request.deadline != task.deadline
            ):
                raise ValueError("task metadata mismatch")
            budget = ModelCallBudget(task.model_call_grant)
            model = build_model_client(settings, budget)
            result = await generate_ad(
                request.prompt,
                index=index,
                model=model,
                deadline=request.deadline,
            )
            result_payload = json.dumps(result, ensure_ascii=False)
            error = None
        except ModelClientError as exc:
            result_payload = "{}"
            error = exc.error
        except Exception as exc:
            result_payload = "{}"
            error = TypedError(
                code=TypedErrorCode.INTERNAL,
                message=f"Generator task failed: {type(exc).__name__}",
            )
        response = SpecialistResult(
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
            payload_json=result_payload,
            error_json=error.model_dump_json() if error else None,
            model_calls_used=budget.consumed if "budget" in locals() else 0,
        )
        replies[key] = (digest, response)
        replies.move_to_end(key)
        while len(replies) > 1000:
            replies.popitem(last=False)
        await ctx.send(sender, response)

    agent.run()


if __name__ == "__main__":
    run()
