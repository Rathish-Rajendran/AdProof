from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from collections import OrderedDict
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import sentry_sdk
from uagents import Context, Model
from uagents_core.contrib.protocols.chat import ChatAcknowledgement, ChatMessage, TextContent

from adproof.domain.models import AuditReport, CampaignInput, ExecutionMode
from adproof.infrastructure.settings import Settings
from adproof.infrastructure.telemetry import initialize_telemetry, record_event
from adproof.orchestrator.gateway import UAgentsGateway
from adproof.orchestrator.workflow import build_live_dependencies, run_campaign
from adproof.transport.models import SpecialistOperation, SpecialistResult, SpecialistTask
from adproof.transport.pending import PendingTaskRegistry
from agents.common import PORTS, load_identities, make_agent, repository_root


class HealthResponse(Model):
    status: str


_FENCED_JSON = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.IGNORECASE | re.DOTALL)
_seen_messages: OrderedDict[tuple[str, str, str], str] = OrderedDict()


def _plain_text(text: str) -> str:
    parts: list[str] = []
    for index in range(0, len(text), 3600):
        parts.append(text[index : index + 3600])
    return "\n".join(parts)


def _campaign_from_text(text: str) -> CampaignInput:
    match = _FENCED_JSON.match(text)
    if match:
        text = match.group(1)
    if text.lstrip().startswith("{"):
        return CampaignInput.model_validate_json(text)
    fields = {}
    for line in text.splitlines():
        key, separator, value = line.partition(":")
        if separator:
            normalized = key.strip().casefold()
            if normalized in {"image", "copy", "page"}:
                fields[normalized] = value.strip()
    if not {"image", "copy", "page"} <= fields.keys():
        raise ValueError("Send a fenced CampaignInput JSON object or Image:/Copy:/Page: fields.")
    return CampaignInput(
        request_id=hashlib.sha256(text.encode("utf-8")).hexdigest()[:24],
        campaign_id="chat-intake",
        creative_version=1,
        creative={"image_url": fields["image"], "ad_copy": fields["copy"]},
        landing_page_url=fields["page"],
        context={
            "platform": "google_ads",
            "jurisdiction": "US",
            "language": "en",
            "audience": "adults",
            "product_category": "electronics",
        },
        repair_mode="audit_only",
    )


def _render_report(report: Any) -> str:
    lines = [
        f"Audit {report.audit_id}: AdProof preflight {report.final_decision.value}",
        f"Workflow: {report.workflow_status.value}; selected candidate: {report.selected_candidate_id}",
        report.final_decision_basis,
        "Scope: Google Ads / US / English / adult-targeted consumer electronics. Not legal advice or platform certification.",
    ]
    if report.original_audit:
        lines.append(f"Original audit: {report.original_audit.decision.value}")
        for issue in report.original_audit.issues:
            lines.append(f"- {issue.category.value} ({issue.action.value}): {issue.explanation}")
    if report.repair_proposal:
        lines.append(f"Repair proposal: {report.repair_proposal.repaired_copy}")
        if report.repair_proposal.image_edit_instructions:
            lines.append("Unchanged-image issues remain:")
            lines.extend(f"- {item}" for item in report.repair_proposal.image_edit_instructions)
    if report.revised_audit:
        lines.append(f"Re-verification: {report.revised_audit.decision.value}")
    if report.errors:
        lines.append("Processing notes:")
        lines.extend(f"- {error.code.value}: {error.message}" for error in report.errors)
    return "\n".join(lines)


def run() -> None:
    settings = Settings.from_env()
    initialize_telemetry(settings, role="orchestrator")
    seeds, addresses = load_identities(settings)
    port = int(os.getenv("ORCHESTRATOR_PORT", PORTS["orchestrator"]))
    agent = make_agent(
        role="orchestrator",
        seed=seeds["orchestrator"],
        addresses=addresses,
        port=port,
        concurrent=True,
    )
    pending = PendingTaskRegistry()
    dependencies = build_live_dependencies(settings)
    dependencies.store.interrupt_nonterminal()
    root = repository_root()

    @agent.on_rest_get("/health", HealthResponse)
    async def health(ctx: Context) -> HealthResponse:
        return HealthResponse(status="ok")

    @agent.on_message(SpecialistResult)
    async def handle_specialist_result(ctx: Context, sender: str, result: SpecialistResult) -> None:
        accepted = await pending.accept(sender, result)
        if accepted:
            record_event(
                "specialist_result_received", role="orchestrator", audit_id=result.audit_id
            )
        else:
            record_event("duplicate_ignored", role="orchestrator", audit_id=result.audit_id)

    @agent.on_message(ChatMessage, replies={ChatAcknowledgement, ChatMessage, SpecialistTask})
    async def handle_chat(ctx: Context, sender: str, message: ChatMessage) -> None:
        await ctx.send(sender, ChatAcknowledgement(acknowledged_msg_id=message.msg_id))
        text = message.text().strip()
        message_key = (sender, str(ctx.session), str(message.msg_id))
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        previous_digest = _seen_messages.get(message_key)
        if previous_digest is not None:
            record_event("duplicate_ignored", role="orchestrator")
            if previous_digest == digest:
                return
            await ctx.send(
                sender,
                ChatMessage(
                    content=[
                        TextContent(
                            type="text", text="Message ID was reused with different content."
                        )
                    ]
                ),
            )
            return
        _seen_messages[message_key] = digest
        _seen_messages.move_to_end(message_key)
        while len(_seen_messages) > 2000:
            _seen_messages.popitem(last=False)

        lowered = text.casefold()
        if len(text.encode("utf-8")) > 16 * 1024:
            reply = "Message exceeds the 16 KiB intake limit."
        elif (
            lowered in {"probe delayed", "probe timeout"}
            and os.getenv("ADPROOF_TRANSPORT_PROBE") == "1"
        ):
            task_id = uuid.uuid4().hex
            probe = "delayed" if lowered.endswith("delayed") else "timeout"
            deadline = datetime.now(UTC) + timedelta(seconds=3)
            task = SpecialistTask(
                schema_version="1.0",
                audit_id=f"probe-{task_id}",
                task_id=task_id,
                request_id=task_id,
                campaign_id="transport-probe",
                candidate_id="probe-candidate",
                creative_version=1,
                phase="ORIGINAL",
                operation=SpecialistOperation.VERIFY,
                attempt=1,
                deadline=deadline,
                execution_mode="TRANSPORT_TEST",
                payload_json=json.dumps({"probe": probe}),
            )
            future = await pending.register(task, addresses["verifier"])
            await ctx.send(addresses["verifier"], task, timeout=3)
            if probe == "timeout":
                result = await pending.wait(task_id, future, timeout=0.3)
                record_event("task_timed_out", role="orchestrator", result="TASK_TIMEOUT")
                reply = f"watchdog=TASK_TIMEOUT; intake_session={ctx.session}"
            else:
                result = await pending.wait(task_id, future, timeout=2)
                if isinstance(result, SpecialistResult):
                    reply = f"specialist={result.payload_json}; intake_session={ctx.session}"
                else:
                    reply = f"specialist_error={result.value}; intake_session={ctx.session}"
        elif lowered in {"help", "?"}:
            reply = (
                "Send `example`, `demo aerobeat [repair]`, `status <audit_id>`, `report <audit_id>`, "
                "a fenced CampaignInput JSON object, or Image:/Copy:/Page: fields."
            )
        elif lowered == "example":
            example_path = root / "schemas/examples/CampaignInput.json"
            reply = example_path.read_text(encoding="utf-8")
        elif lowered.startswith(("status ", "report ")):
            command, audit_id = text.split(maxsplit=1)
            stored = dependencies.store.get_workflow(
                audit_id.strip(),
                owner=sender,
                session_id=str(ctx.session),
            )
            if stored is None:
                reply = "No audit with that ID is available to this chat session."
            elif command.casefold() == "status":
                reply = f"Audit {audit_id.strip()}: {stored['state']}"
            else:
                report = stored.get("payload", {}).get("report")
                reply = (
                    _render_report(AuditReport.model_validate(report))
                    if report
                    else "No report is available yet."
                )
        else:
            try:
                if lowered.startswith("demo aerobeat"):
                    repair_mode = "repair_once" if "repair" in lowered else "audit_only"
                    demo_path = root / "data/fixtures/demo_campaign.json"
                    campaign = CampaignInput.model_validate_json(
                        demo_path.read_text(encoding="utf-8")
                    )
                    if repair_mode == "repair_once":
                        campaign = campaign.model_copy(
                            update={
                                "creative": campaign.creative.model_copy(
                                    update={
                                        "image_url": campaign.creative.image_url.replace(
                                            "aerobeat-neutral.png", "aerobeat-only49.png"
                                        ),
                                        "ad_copy": "AeroBeat AB-01 headphones. Only $49.",
                                    }
                                )
                            }
                        )
                    campaign = campaign.model_copy(
                        update={
                            "request_id": hashlib.sha256(
                                f"{campaign.request_id}:{message.msg_id}".encode()
                            ).hexdigest()[:24],
                            "repair_mode": repair_mode,
                        }
                    )
                else:
                    campaign = _campaign_from_text(text)
                gateway = UAgentsGateway(
                    context=ctx,
                    pending=pending,
                    verifier_address=addresses["verifier"],
                    remediator_address=addresses["remediator"],
                    budget=dependencies.budget,
                    execution_mode=ExecutionMode.LIVE.value,
                )
                with sentry_sdk.start_transaction(name="adproof audit", op="adproof.intake"):
                    trace_parent = sentry_sdk.get_traceparent()
                    if settings.sentry_dsn and trace_parent:
                        print(f"ADPROOF_TRACE_PARENT={trace_parent}", flush=True)
                    report = await run_campaign(
                        campaign,
                        owner=sender,
                        session_id=str(ctx.session),
                        dependencies=replace(dependencies, gateway=gateway),
                    )
                reply = _render_report(report)
            except Exception as exc:
                record_event("audit_failed", role="orchestrator", result=type(exc).__name__)
                reply = f"Request could not be processed ({type(exc).__name__}). Send `help` for accepted inputs."
        for chunk in _plain_text(reply).splitlines():
            await ctx.send(sender, ChatMessage(content=[TextContent(type="text", text=chunk)]))

    agent.run()


if __name__ == "__main__":
    run()
