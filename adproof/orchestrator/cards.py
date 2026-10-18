from __future__ import annotations

import hashlib
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from uagents_core.contrib.protocols.chat import ChatMessage, MetadataContent
from uagents_core.contrib.protocols.chat.cards import (
    CtaAction,
    DetailCardPayload,
    DetailSummaryRow,
    create_card_content,
    extract_card_response,
    validate_card_payload,
)

from adproof.domain.models import AuditReport, CampaignInput, Decision

MAX_CARD_BYTES = 8 * 1024


class CardAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["show_report", "run_repair", "status"]
    action_id: str = Field(min_length=1, max_length=256)
    audit_id: str = Field(min_length=1, max_length=128)


def create_result_card(report: AuditReport) -> MetadataContent:
    audit_id = report.audit_id
    ctas = [
        _action(audit_id, "show_report", "Show report"),
        _action(audit_id, "status", "Status"),
    ]
    if (
        report.original_audit is not None
        and report.original_audit.decision == Decision.FIX_REQUIRED
        and report.repair_proposal is None
    ):
        ctas.insert(1, _action(audit_id, "run_repair", "Run one repair"))
    payload = DetailCardPayload(
        title="AdProof audit",
        summary_rows=[
            DetailSummaryRow(label="Decision", value=report.final_decision.value),
            DetailSummaryRow(label="Workflow", value=report.workflow_status.value),
            DetailSummaryRow(label="Audit ID", value=audit_id),
        ],
        ctas=ctas,
    )
    payload_dict = payload.model_dump(mode="json", exclude_none=True)
    validate_card_payload("detail", payload_dict)
    if len(payload.model_dump_json(exclude_none=True).encode("utf-8")) > MAX_CARD_BYTES:
        raise ValueError("card payload exceeds its byte limit")
    return create_card_content(payload, card_id=uuid.uuid4())


def extract_card_action(message: ChatMessage) -> CardAction | None:
    for content in message.content:
        if not isinstance(content, MetadataContent):
            continue
        response = extract_card_response(content)
        if response is None or response.cancelled or response.selection is None:
            continue
        try:
            action = CardAction.model_validate(response.selection)
        except ValidationError as exc:
            raise ValueError("card response is invalid") from exc
        if action.action_id != f"{action.audit_id}:{action.action}":
            raise ValueError("card action ID does not match its action and audit")
        return action
    return None


def _action(audit_id: str, action: str, label: str) -> CtaAction:
    return CtaAction(
        label=label,
        selection={
            "action": action,
            "action_id": f"{audit_id}:{action}",
            "audit_id": audit_id,
        },
    )


async def handle_card_action(
    action: CardAction,
    *,
    owner: str,
    session_id: str,
    store: Any,
    render_report: Any,
    run_repair: Any,
) -> str:
    stored = store.get_workflow(action.audit_id, owner=owner, session_id=session_id)
    if stored is None:
        return "No audit with that ID is available to this chat session."
    if action.action_id != f"{action.audit_id}:{action.action}":
        return "This card action is invalid."
    digest = hashlib.sha256(
        f"{action.action}\n{action.audit_id}\n{action.action_id}".encode()
    ).hexdigest()
    claimed = store.claim_card_action(
        owner=owner,
        session_id=session_id,
        action_id=action.action_id,
        digest=digest,
    )
    if claimed is False:
        return "This card action was already handled."
    if claimed is not True:
        return "This card action ID was reused with different content."
    if action.action == "status":
        return f"Audit {action.audit_id}: {stored['state']}"
    report_data = stored.get("payload", {}).get("report")
    if not report_data:
        return "No report is available yet."
    report = AuditReport.model_validate(report_data)
    if action.action == "show_report":
        return render_report(report)
    if (
        report.original_audit is None
        or report.original_audit.decision != Decision.FIX_REQUIRED
        or report.repair_proposal is not None
        or report.revised_audit is not None
    ):
        return "One copy-only repair is available only for an unrepaired FIX_REQUIRED audit."
    campaign_data = stored.get("payload", {}).get("campaign")
    if not campaign_data:
        return "The original campaign input is unavailable; a repair cannot be started."
    campaign = CampaignInput.model_validate(campaign_data).model_copy(
        update={
            "request_id": f"{campaign_data['request_id']}-card-{uuid.uuid4().hex[:8]}",
            "repair_mode": "repair_once",
        }
    )
    return await run_repair(campaign)
