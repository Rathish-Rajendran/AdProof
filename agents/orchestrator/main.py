from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import sentry_sdk
from uagents import Context, Model, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    EndSessionContent,
    MetadataContent,
    StartSessionContent,
    TextContent,
    chat_protocol_spec,
)

from adproof.domain.models import AuditReport, CampaignInput, ExecutionMode
from adproof.infrastructure.settings import Settings
from adproof.infrastructure.telemetry import initialize_telemetry, record_event
from adproof.orchestrator.cards import (
    card_action_from_text,
    extract_card_action,
    handle_card_action,
)
from adproof.orchestrator.gateway import UAgentsGateway
from adproof.orchestrator.limits import OwnerAuditLimiter
from adproof.orchestrator.report_view import render_report
from adproof.orchestrator.workflow import build_live_dependencies, run_campaign
from adproof.transport.models import SpecialistOperation, SpecialistResult, SpecialistTask
from adproof.transport.pending import PendingTaskRegistry
from agents.common import PORTS, load_identities, make_agent, repository_root


class HealthResponse(Model):
    status: str


_LEADING_MENTIONS = re.compile(r"^(?:\s*@[\w.\-]+[,:]?)+\s*")
_FENCED_JSON = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.IGNORECASE | re.DOTALL)
_SCOPE_LINE = (
    "_Scope: Google Ads · US · English · adult consumer electronics. "
    "Bounded preflight — not legal advice or platform certification._"
)
_owner_limiter = OwnerAuditLimiter(limit=2)


def _text_chunks(text: str, limit: int = 3600) -> list[str]:
    """Group blank-line-separated blocks into messages; a block is never split."""
    chunks = [""]
    for block in text.split("\n\n"):
        candidate = f"{chunks[-1]}\n\n{block}" if chunks[-1] else block
        if len(candidate) <= limit or not chunks[-1]:
            chunks[-1] = candidate
        else:
            chunks.append(block)
    return chunks


def strip_leading_mentions(text: str) -> str:
    return _LEADING_MENTIONS.sub("", text, count=1).strip()


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
    return render_report(report)


def _help_message() -> str:
    return "\n".join(
        [
            "## AdProof commands",
            "- `demo aerobeat` — Audit the unsafe AeroBeat ad and attempt one copy-only repair.",
            "- `demo aerobeat49` — Show that a copy repair cannot fix the `$49` image.",
            "- `demo aerobeat correct` — Audit the already-correct AeroBeat ad.",
            "- `example` — Show an example campaign input.",
            "- `status <audit_id>` — Show an audit's current state.",
            "- `report <audit_id>` — Show a saved audit report.",
            "- Fenced `CampaignInput` JSON — Submit a campaign as JSON.",
            "- `Image:` / `Copy:` / `Page:` — Submit one field per line.",
            "",
            _SCOPE_LINE,
        ]
    )


def _welcome_message() -> str:
    return "\n".join(
        [
            "## Welcome to AdProof",
            "Send `help` for commands.",
            "",
            _SCOPE_LINE,
        ]
    )


def _safe_text_card_action(text: str):
    """Return a text-echoed card action, None if absent, or False if malformed."""
    try:
        return card_action_from_text(text)
    except ValueError:
        return False


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
    chat_protocol = Protocol(spec=chat_protocol_spec)

    async def execute_campaign(
        campaign: CampaignInput, *, owner: str, session_id: str, ctx: Context
    ) -> AuditReport | None:
        if not await _owner_limiter.acquire(owner):
            return None
        try:
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
                return await run_campaign(
                    campaign,
                    owner=owner,
                    session_id=session_id,
                    dependencies=replace(dependencies, gateway=gateway),
                )
        finally:
            await _owner_limiter.release(owner)

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

    @chat_protocol.on_message(ChatAcknowledgement)
    async def handle_chat_acknowledgement(
        ctx: Context, sender: str, message: ChatAcknowledgement
    ) -> None:
        return

    @chat_protocol.on_message(ChatMessage)
    async def handle_chat(ctx: Context, sender: str, message: ChatMessage) -> None:
        await ctx.send(sender, ChatAcknowledgement(acknowledged_msg_id=message.msg_id))
        text = strip_leading_mentions(message.text())
        session_id = str(ctx.session)
        digest = hashlib.sha256(
            json.dumps(message.dict(), sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        message_status = dependencies.store.claim_chat_message(
            sender=sender,
            session_id=session_id,
            msg_id=str(message.msg_id),
            digest=digest,
        )
        if message_status == "DUPLICATE":
            record_event("duplicate_ignored", role="orchestrator")
            return
        if message_status == "CONFLICT":
            reply = "Message ID was reused with different content."
            await _send_terminal(ctx, sender, reply)
            return
        lowered = text.casefold()
        result_card = None
        if len(text.encode("utf-8")) > 16 * 1024:
            reply = "Message exceeds the 16 KiB intake limit."
        elif any(isinstance(item, StartSessionContent) for item in message.content):
            reply = _welcome_message()
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
            reply = _help_message()
        elif lowered == "example":
            example_path = root / "schemas/examples/CampaignInput.json"
            reply = "```json\n" + example_path.read_text(encoding="utf-8").strip() + "\n```"
        elif (text_card_action := _safe_text_card_action(text)) is not False and (
            text_card_action is not None
            or any(
                isinstance(item, MetadataContent)
                and item.metadata.get("card_protocol_version") == "1"
                and "card_kind" not in item.metadata
                for item in message.content
            )
        ):
            try:
                action = text_card_action or extract_card_action(message)
                if action is None:
                    reply = "Card action was not recognized."
                else:

                    async def run_card_repair(campaign: CampaignInput) -> str:
                        report = await execute_campaign(
                            campaign, owner=sender, session_id=session_id, ctx=ctx
                        )
                        if report is None:
                            return "The per-owner concurrent-audit limit is currently full."
                        return _render_report(report)

                    reply = await handle_card_action(
                        action,
                        owner=sender,
                        session_id=session_id,
                        store=dependencies.store,
                        render_report=_render_report,
                        run_repair=run_card_repair,
                    )
            except ValueError:
                reply = "Card action was invalid."
        elif lowered.startswith(("status ", "report ")):
            command, audit_id = text.split(maxsplit=1)
            stored = dependencies.store.get_workflow(
                audit_id.strip(),
                owner=sender,
                session_id=session_id,
            )
            if stored is None:
                reply = "No audit with that ID is available to this chat session."
            elif command.casefold() == "status":
                reply = f"**Audit** `{audit_id.strip()}`: {stored['state']}"
            else:
                report = stored.get("payload", {}).get("report")
                if report:
                    parsed_report = AuditReport.model_validate(report)
                    reply = _render_report(parsed_report)
                else:
                    reply = "No report is available yet."
        else:
            try:
                demo_cases = {
                    "demo aerobeat": "case01_unsafe_neutral.json",
                    "demo aerobeat49": "case03_unsafe_only49.json",
                    "demo aerobeat correct": "case04_correct_neutral.json",
                }
                if lowered in demo_cases:
                    demo_path = root / "data/fixtures/cases" / demo_cases[lowered]
                    campaign = CampaignInput.model_validate_json(
                        demo_path.read_text(encoding="utf-8")
                    )
                    campaign = campaign.model_copy(
                        update={
                            "request_id": hashlib.sha256(
                                f"{campaign.request_id}:{message.msg_id}".encode()
                            ).hexdigest()[:24],
                        }
                    )
                else:
                    campaign = _campaign_from_text(text)
                report = await execute_campaign(
                    campaign, owner=sender, session_id=session_id, ctx=ctx
                )
                if report is None:
                    reply = "The per-owner concurrent-audit limit is currently full."
                else:
                    reply = _render_report(report)
            except Exception as exc:
                record_event("audit_failed", role="orchestrator", result=type(exc).__name__)
                reply = f"Request could not be processed ({type(exc).__name__}). Send `help` for accepted inputs."
        await _send_terminal(ctx, sender, reply, card=result_card)
        dependencies.store.complete_chat_message(
            sender=sender,
            session_id=session_id,
            msg_id=str(message.msg_id),
            response={"text": reply},
        )

    agent.include(chat_protocol, publish_manifest=True)

    agent.run()


async def _send_terminal(ctx: Context, sender: str, reply: str, *, card: Any | None = None) -> None:
    chunks = _text_chunks(reply)
    for chunk in chunks[:-1]:
        content = [TextContent(type="text", text=chunk)] if chunk else []
        await ctx.send(sender, ChatMessage(content=content))
    content = [TextContent(type="text", text=chunks[-1])] if chunks[-1] else []
    if card is not None:
        content.append(card)
    content.append(EndSessionContent())
    await ctx.send(sender, ChatMessage(content=content))


if __name__ == "__main__":
    run()
