from adproof.domain.models import (
    AuditReport,
    Coverage,
    CoverageItem,
    CoverageStatus,
    CreativeCandidate,
    Decision,
    ExecutionMode,
    Issue,
    IssueAction,
    IssueCategory,
    Phase,
    RepairResult,
    Severity,
    TypedError,
    TypedErrorCode,
    VerificationResult,
    WorkflowStatus,
)
from agents.orchestrator.main import _help_message, _render_report, _welcome_message


def _coverage() -> Coverage:
    item = CoverageItem(status=CoverageStatus.CHECKED)
    return Coverage(
        ad_text=item,
        landing_page=item,
        supporting_documents=item,
        image=item,
        platform_policy=item,
    )


def _candidate(candidate_id: str, *, phase: Phase, ad_copy: str) -> CreativeCandidate:
    return CreativeCandidate(
        campaign_id="campaign-case-1",
        candidate_id=candidate_id,
        creative_version=1,
        phase=phase,
        ad_copy=ad_copy,
        source_image_sha256="a" * 64,
        model_input_sha256="b" * 64,
        asset_ref="https://example.com/aerobeat.png",
        context={
            "platform": "google_ads",
            "jurisdiction": "US",
            "language": "en",
            "audience": "adults",
            "product_category": "electronics",
        },
    )


def _audit(
    *,
    candidate_id: str,
    phase: Phase,
    decision: Decision,
    issues: list[Issue] | None = None,
) -> VerificationResult:
    return VerificationResult(
        audit_id="audit-case-1",
        campaign_id="campaign-case-1",
        candidate_id=candidate_id,
        creative_version=1,
        phase=phase,
        decision=decision,
        audit_complete=True,
        evidence_scope="Pinned landing-page evidence and creative image.",
        coverage=_coverage(),
        policy_catalog_version="test-policy-v1",
        issues=issues or [],
    )


def _report(
    *,
    final_decision: Decision = Decision.PASS,
    original_audit: VerificationResult | None = None,
    repair_proposal: RepairResult | None = None,
    revised_audit: VerificationResult | None = None,
    errors: list[TypedError] | None = None,
) -> AuditReport:
    original_candidate = _candidate(
        "candidate-original",
        phase=Phase.ORIGINAL,
        ad_copy="Completely waterproof; 48 hours; recommended by 1,000 athletes; 50% off.",
    )
    return AuditReport(
        audit_id="audit-case-1",
        execution_mode=ExecutionMode.LIVE,
        workflow_status=WorkflowStatus.COMPLETED,
        scope="Google Ads / US / English / adult consumer electronics",
        original_candidate=original_candidate,
        original_audit=original_audit,
        repair_proposal=repair_proposal,
        revised_candidate=(
            _candidate(
                "candidate-repaired",
                phase=Phase.REPAIRED,
                ad_copy="Splash-resistant, up to 30 hours, now $60—25% off.",
            )
            if revised_audit
            else None
        ),
        revised_audit=revised_audit,
        selected_candidate_id="candidate-repaired" if revised_audit else "candidate-original",
        final_decision=final_decision,
        final_decision_basis=(
            "The repaired copy passed an independent re-check."
            if final_decision == Decision.PASS
            else "Gemini quota exhaustion prevented verification."
        ),
        repair_verified=revised_audit is not None and revised_audit.decision == Decision.PASS,
        errors=errors or [],
    )


def test_render_case_one_report_as_numbered_markdown_with_repair_and_recheck():
    original_issues = [
        Issue(
            id="waterproof",
            category=IssueCategory.AD_LANDING_PAGE_CONTRADICTION,
            severity=Severity.HIGH,
            explanation="The page says the headphones are not waterproof.",
            action=IssueAction.FIX,
            policy_reference="landing_page_consistency",
        ),
        Issue(
            id="battery",
            category=IssueCategory.AD_LANDING_PAGE_CONTRADICTION,
            severity=Severity.HIGH,
            explanation="The 48-hour battery claim is not established.",
            action=IssueAction.FIX,
            policy_reference="claim_landing_page_consistency",
        ),
        Issue(
            id="endorsement",
            category=IssueCategory.UNVERIFIED_ENDORSEMENT,
            severity=Severity.MEDIUM,
            explanation="No evidence supports the athlete endorsement.",
            action=IssueAction.FIX,
            policy_reference="endorsement_evidence",
        ),
        Issue(
            id="discount",
            category=IssueCategory.PRICE_DISCOUNT_MISMATCH,
            severity=Severity.HIGH,
            explanation="The listed prices establish 25% off, not 50%.",
            action=IssueAction.FIX,
            policy_reference="discount_accuracy",
        ),
    ]
    original_audit = _audit(
        candidate_id="candidate-original",
        phase=Phase.ORIGINAL,
        decision=Decision.FIX_REQUIRED,
        issues=original_issues,
    )
    revised_audit = _audit(
        candidate_id="candidate-repaired",
        phase=Phase.REPAIRED,
        decision=Decision.PASS,
    )
    repair_proposal = RepairResult(
        audit_id="audit-case-1",
        original_candidate_id="candidate-original",
        candidate_id="candidate-repaired",
        repaired_copy="Splash-resistant. Up to 30 hours. Now $60—25% off!",
        image_edit_instructions=["The image shows a $49 price that copy cannot change."],
        model_version="gemini-3.6-flash",
        prompt_version="test",
    )

    rendered = _render_report(
        _report(
            original_audit=original_audit,
            repair_proposal=repair_proposal,
            revised_audit=revised_audit,
        )
    )

    assert "## AdProof preflight: **PASS**" in rendered
    assert "### Original audit — FIX_REQUIRED" in rendered
    assert "### Proposed repair (copy only)" in rendered
    assert "### Independent re-check — PASS" in rendered
    assert "> Splash-resistant. Up to 30 hours. Now $60—25% off!" in rendered
    assert "Image issues a copy edit cannot fix:" in rendered
    assert "No unresolved issues within the checked scope." in rendered
    original_section = rendered.split("### Original audit — FIX_REQUIRED\n", 1)[1].split(
        "\n\n### Proposed repair", 1
    )[0]
    assert [line.split(".", 1)[0] for line in original_section.splitlines()] == [
        "1",
        "2",
        "3",
        "4",
    ]
    assert "**Ad Landing Page Contradiction** (fix)" in original_section
    assert "**Unverified Endorsement** (fix)" in original_section
    assert "**Price Discount Mismatch** (fix)" in original_section
    for rule_id in (
        "landing_page_consistency",
        "claim_landing_page_consistency",
        "endorsement_evidence",
        "discount_accuracy",
    ):
        assert f"_Rule: {rule_id}_" in original_section
    assert "PRICE_DISCOUNT_MISMATCH" not in rendered
    assert "selected candidate" not in rendered


def test_quota_failure_report_deduplicates_notes_and_omits_repair():
    error = TypedError(
        code=TypedErrorCode.MODEL_UNAVAILABLE,
        message="Gemini quota exhausted.",
        retryable=False,
    )
    rendered = _render_report(
        _report(
            final_decision=Decision.HUMAN_REVIEW,
            errors=[error, error],
        )
    )

    assert "## AdProof preflight: **HUMAN_REVIEW**" in rendered
    assert "### Processing notes" in rendered
    assert rendered.count("`MODEL_UNAVAILABLE` — Gemini quota exhausted.") == 1
    assert "### Proposed repair (copy only)" not in rendered


def test_help_and_welcome_are_markdown_and_include_scope():
    help_message = _help_message()

    assert "## AdProof commands" in help_message
    assert "`demo aerobeat`" in help_message
    assert "`demo aerobeat49`" in help_message
    assert "`demo aerobeat correct`" in help_message
    assert "`status <audit_id>`" in help_message
    assert "`report <audit_id>`" in help_message
    assert "Fenced `CampaignInput` JSON" in help_message
    assert "`Image:` / `Copy:` / `Page:`" in help_message
    assert help_message.endswith(
        "_Scope: Google Ads · US · English · adult consumer electronics. "
        "Bounded preflight — not legal advice or platform certification._"
    )

    welcome_message = _welcome_message()
    assert "## Welcome to AdProof" in welcome_message
    assert welcome_message.endswith(help_message.splitlines()[-1])
