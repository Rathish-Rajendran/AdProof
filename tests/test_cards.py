import asyncio
from pathlib import Path

import pytest
from pydantic import ValidationError
from uagents_core.contrib.protocols.chat import (
    ChatMessage,
    EndSessionContent,
    MetadataContent,
    TextContent,
)
from uagents_core.contrib.protocols.chat.cards import (
    DetailCardPayload,
    create_card_response_content,
    extract_card,
    extract_card_response,
    validate_card_payload,
)

from adproof.domain.models import (
    AuditReport,
    CampaignContext,
    CampaignInput,
    Coverage,
    CoverageItem,
    CoverageStatus,
    CreativeCandidate,
    Decision,
    ExecutionMode,
    Phase,
    VerificationResult,
    WorkflowStatus,
)
from adproof.infrastructure.store import SQLiteStore
from adproof.orchestrator.cards import (
    CardAction,
    create_result_card,
    extract_card_action,
    handle_card_action,
)
from adproof.orchestrator.limits import OwnerAuditLimiter
from agents.orchestrator.main import _send_terminal


def _report() -> AuditReport:
    context = CampaignContext(
        platform="google_ads",
        jurisdiction="US",
        language="en",
        audience="adults",
        product_category="electronics",
    )
    candidate = CreativeCandidate(
        campaign_id="campaign",
        candidate_id="candidate",
        creative_version=1,
        phase=Phase.ORIGINAL,
        ad_copy="Unsafe copy",
        source_image_sha256="a" * 64,
        model_input_sha256="b" * 64,
        asset_ref="https://example.com/image.png",
        context=context,
    )
    coverage = Coverage(
        ad_text=CoverageItem(status=CoverageStatus.CHECKED),
        landing_page=CoverageItem(status=CoverageStatus.CHECKED),
        supporting_documents=CoverageItem(status=CoverageStatus.NOT_APPLICABLE),
        image=CoverageItem(status=CoverageStatus.CHECKED),
        platform_policy=CoverageItem(status=CoverageStatus.PARTIAL),
    )
    original = VerificationResult(
        audit_id="audit",
        campaign_id="campaign",
        candidate_id="candidate",
        creative_version=1,
        phase=Phase.ORIGINAL,
        decision=Decision.FIX_REQUIRED,
        audit_complete=True,
        evidence_scope="Bounded test evidence",
        coverage=coverage,
        policy_catalog_version="test",
    )
    return AuditReport(
        audit_id="audit",
        execution_mode=ExecutionMode.MOCK,
        workflow_status=WorkflowStatus.COMPLETED,
        scope="test",
        original_candidate=candidate,
        original_audit=original,
        selected_candidate_id="candidate",
        final_decision=Decision.FIX_REQUIRED,
        final_decision_basis="The copy requires repair.",
        repair_verified=False,
    )


def _campaign() -> CampaignInput:
    example = Path(__file__).parents[1] / "schemas/examples/CampaignInput.json"
    return CampaignInput.model_validate_json(example.read_text(encoding="utf-8"))


def _store(tmp_path):
    store = SQLiteStore(tmp_path / "store.sqlite3")
    report = _report()
    campaign = _campaign()
    store.save_workflow(
        audit_id="audit",
        owner="owner",
        session_id="session",
        state="COMPLETED",
        payload={
            "campaign": campaign.model_dump(mode="json"),
            "report": report.model_dump(mode="json"),
        },
    )
    return store, report


def test_official_card_round_trip_and_validation(tmp_path):
    _, report = _store(tmp_path)
    card_content = create_result_card(report)
    card = extract_card(card_content)
    assert card is not None
    assert isinstance(card.payload, DetailCardPayload)
    payload = validate_card_payload(
        "detail", card.payload.model_dump(mode="json", exclude_none=True)
    )
    assert isinstance(payload, DetailCardPayload)

    assert card_content.metadata["card_protocol_version"] == "1"
    assert card_content.metadata["card_kind"] == "detail"
    assert [item.label for item in payload.ctas] == [
        "Show report",
        "Run one repair",
        "Status",
    ]
    assert all(isinstance(value, str) for cta in payload.ctas for value in cta.selection.values())
    repair_cta = next(cta for cta in payload.ctas if cta.label == "Run one repair")
    response_content = create_card_response_content(
        card_id=card.card_id,
        selection=repair_cta.selection,
    )
    response = extract_card_response(response_content)
    assert response is not None
    assert response.selection == repair_cta.selection
    action = extract_card_action(ChatMessage(content=[response_content]))
    assert action == CardAction(
        action="run_repair",
        action_id="audit:run_repair",
        audit_id="audit",
    )


def _official_repair_action() -> CardAction:
    card = extract_card(create_result_card(_report()))
    assert card is not None and isinstance(card.payload, DetailCardPayload)
    cta = next(cta for cta in card.payload.ctas if cta.label == "Run one repair")
    response_content = create_card_response_content(
        card_id=card.card_id,
        selection=cta.selection,
    )
    action = extract_card_action(ChatMessage(content=[response_content]))
    assert action is not None
    return action


def test_card_action_is_owner_and_session_bound(tmp_path):
    store, _ = _store(tmp_path)
    called = False

    async def run_repair(campaign):
        nonlocal called
        called = True
        return "repaired"

    action = _official_repair_action()
    result = asyncio.run(
        handle_card_action(
            action,
            owner="owner",
            session_id="foreign-session",
            store=store,
            render_report=lambda report: "report",
            run_repair=run_repair,
        )
    )
    assert "No audit" in result
    assert called is False


def test_duplicate_run_repair_action_never_starts_a_second_repair(tmp_path):
    store, _ = _store(tmp_path)
    calls = 0

    async def run_repair(campaign):
        nonlocal calls
        calls += 1
        assert campaign.repair_mode == "repair_once"
        return "repair started"

    action = _official_repair_action()

    async def run_twice():
        first = await handle_card_action(
            action,
            owner="owner",
            session_id="session",
            store=store,
            render_report=lambda report: "report",
            run_repair=run_repair,
        )
        second = await handle_card_action(
            action,
            owner="owner",
            session_id="session",
            store=store,
            render_report=lambda report: "report",
            run_repair=run_repair,
        )
        return first, second

    first, second = asyncio.run(run_twice())
    assert first == "repair started"
    assert second == "This card action was already handled."
    assert calls == 1


def test_official_card_payload_validator_rejects_missing_ctas():
    with pytest.raises(ValidationError):
        validate_card_payload("detail", {"title": "Audit", "ctas": []})


@pytest.mark.asyncio
async def test_reply_sends_plain_text_then_card_and_ends_session(tmp_path):
    _, report = _store(tmp_path)
    card = create_result_card(report)

    class Context:
        sent = []

        async def send(self, sender, message):
            self.sent.append((sender, message))

    ctx = Context()
    await _send_terminal(ctx, "recipient", "Audit report", card=card)

    assert len(ctx.sent) == 1
    content = ctx.sent[0][1].content
    assert isinstance(content[0], TextContent)
    assert content[0].text == "Audit report"
    assert isinstance(content[1], MetadataContent)
    assert isinstance(content[2], EndSessionContent)


@pytest.mark.asyncio
async def test_owner_audit_limit_is_independent_and_released():
    limiter = OwnerAuditLimiter(limit=1)
    assert await limiter.acquire("alice")
    assert not await limiter.acquire("alice")
    assert await limiter.acquire("bob")
    await limiter.release("alice")
    assert await limiter.acquire("alice")
    await limiter.release("alice")
    await limiter.release("bob")


def test_asi_one_text_echoed_selection_is_parsed_as_card_action():
    from adproof.orchestrator.cards import card_action_from_text

    audit = "dbe34b6648aa4af29f7f24f81f8e9dba"
    text = (
        f'{{"action":"show_report","action_id":"{audit}:show_report",'
        f'"audit_id":"{audit}","app":"asi1"}}'
    )
    action = card_action_from_text(text)
    assert action is not None and action.action == "show_report" and action.audit_id == audit
    assert card_action_from_text("demo aerobeat") is None
    assert card_action_from_text('{"campaign": 1}') is None
    import pytest

    with pytest.raises(ValueError):
        card_action_from_text(
            f'{{"action":"status","action_id":"{audit}:show_report","audit_id":"{audit}"}}'
        )
