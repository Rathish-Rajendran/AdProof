import json
from datetime import UTC, datetime
from pathlib import Path

from adproof.domain.models import (
    AuditReport,
    CampaignContext,
    Claim,
    ClaimSource,
    ClaimStatus,
    ClaimType,
    Coverage,
    CoverageItem,
    CoverageStatus,
    CreativeCandidate,
    Decision,
    Evidence,
    ExecutionMode,
    Issue,
    IssueAction,
    IssueCategory,
    Phase,
    PolicyCheck,
    PolicyEnforcement,
    PolicyReviewStatus,
    Severity,
    TypedError,
    TypedErrorCode,
    VerificationResult,
    WorkflowStatus,
)
from adproof.orchestrator.report_view import (
    READY_THRESHOLD,
    _confidence,
    render_generation_failure,
    report_summary,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY_ID = "GADS_MISLEADING_AD_DESIGN_AD_LANDING_INCONSISTENCY"
POLICY_TITLE = (
    "Google Ads Misrepresentation — Misleading ad design: inconsistencies between "
    "the ad and the landing page"
)


def _coverage() -> Coverage:
    checked = CoverageItem(status=CoverageStatus.CHECKED)
    return Coverage(
        ad_text=checked,
        landing_page=checked,
        supporting_documents=checked,
        image=checked,
        platform_policy=checked,
    )


def _evidence(*, excerpt: str = "Up to 30 hours of battery life with ANC off.") -> Evidence:
    return Evidence(
        id="evidence-1",
        source_url="https://aerobeat.example/products/ab-01",
        excerpt=excerpt,
        source_type="company_corpus",
        retrieved_at=datetime.now(UTC),
        document_id="aerobeat-ab01-product",
        snapshot_id="snapshot-1",
        content_sha256="a" * 64,
        locator="aerobeat-ab01-product#1",
    )


def _claim(
    status: ClaimStatus = ClaimStatus.SUPPORTED,
    *,
    evidence_ids: list[str] | None = None,
    text: str = "Up to 30 hours with ANC off.",
) -> Claim:
    return Claim(
        id="claim-1",
        claim=text,
        source=ClaimSource.AD_TEXT,
        claim_type=ClaimType.PERFORMANCE,
        status=status,
        evidence_ids=["evidence-1"] if evidence_ids is None else evidence_ids,
        explanation="The claim is supported by the product page."
        if status == ClaimStatus.SUPPORTED
        else "No evidence establishes this claim.",
    )


def _policy_check(
    *,
    review_status: PolicyReviewStatus = PolicyReviewStatus.ACTIVE,
    checked: bool = True,
    predicate_established: bool = False,
    finding: str | None = None,
) -> PolicyCheck:
    return PolicyCheck(
        rule_id=POLICY_ID,
        applicable=True,
        review_status=review_status,
        enforcement=PolicyEnforcement.FIX,
        checked=checked,
        predicate_established=predicate_established,
        finding=finding,
    )


def _report(
    decision: Decision = Decision.PASS,
    *,
    ad_copy: str = "AeroBeat AB-01 offers up to 30 hours.",
    claims: list[Claim] | None = None,
    policies: list[PolicyCheck] | None = None,
    audit_errors: list[TypedError] | None = None,
    report_errors: list[TypedError] | None = None,
    evidence: list[Evidence] | None = None,
    issues=None,
    with_generation: bool = False,
) -> AuditReport:
    candidate = CreativeCandidate(
        campaign_id="campaign-1",
        candidate_id="candidate-1",
        creative_version=1,
        phase=Phase.ORIGINAL,
        ad_copy=ad_copy,
        source_image_sha256="b" * 64,
        model_input_sha256="c" * 64,
        asset_ref="https://aerobeat.example/products/ab-01",
        context=CampaignContext(
            platform="google_ads",
            jurisdiction="US",
            language="en",
            audience="adults",
            product_category="electronics",
        ),
    )
    audit = VerificationResult(
        audit_id="audit-1",
        campaign_id="campaign-1",
        candidate_id="candidate-1",
        creative_version=1,
        phase=Phase.ORIGINAL,
        decision=decision,
        audit_complete=True,
        evidence_scope="Product page and policy pack.",
        claims=claims or [],
        evidence=evidence or [],
        issues=issues or [],
        coverage=_coverage(),
        policy_checks=policies or [],
        policy_catalog_version="test-v1",
        errors=audit_errors or [],
    )
    return AuditReport(
        audit_id="audit-1",
        execution_mode=ExecutionMode.LIVE,
        workflow_status=WorkflowStatus.COMPLETED,
        scope="Google Ads / US / adult electronics.",
        original_candidate=candidate,
        original_audit=audit,
        selected_candidate_id=candidate.candidate_id,
        final_decision=decision,
        final_decision_basis="Deterministic report test.",
        repair_verified=False,
        errors=report_errors or [],
        generation_request=(
            {
                "prompt": "Generate an ad for AeroBeat AB-01.",
                "platform": "google_ads",
                "jurisdiction": "US",
                "language": "en",
                "audience": "adults",
            }
            if with_generation
            else None
        ),
        generated_ad=(
            {
                "headlines": ["AeroBeat AB-01"],
                "final_url": "https://aerobeat.example/products/ab-01",
                "sources": ["aerobeat-ab01-product#1"],
            }
            if with_generation
            else None
        ),
    )


def test_supported_pass_is_ready_with_exact_summary_and_claim_provenance():
    report = _report(
        claims=[_claim(text="Battery life is up to 30 hours with ANC off.")],
        policies=[_policy_check()],
        evidence=[
            _evidence(
                excerpt="Battery life is up to 30 hours with active noise cancellation (ANC) off"
            )
        ],
        with_generation=True,
    )

    result = report_summary(report)

    assert READY_THRESHOLD == 95
    assert result["needs_review"] is False
    assert result["confidence"] == 100
    assert result["summary"] == (
        "Ready to run: all 1 claims are backed by company data; 1 Google Ads rules passed."
    )
    assert result["claims"] == [
        {
            "claim": "Battery life is up to 30 hours with ANC off.",
            "quote": "Battery life is up to 30 hours with active noise cancellation (ANC) off",
            "source": ("AeroBeat AB-01 headphones product page › Battery"),
        }
    ]
    assert result["compliance"] == "OK"
    assert result["ad"] == {
        "platform": "google_ads",
        "headlines": ["AeroBeat AB-01"],
        "final_url": "https://aerobeat.example/products/ab-01",
    }
    assert list(result) == [
        "audit_id",
        "needs_review",
        "confidence",
        "summary",
        "ad",
        "compliance",
        "claims",
    ]
    assert "#" not in json.dumps(result, ensure_ascii=False)


def test_insufficient_claim_fails_and_five_check_confidence_formula_is_80():
    report = _report(
        claims=[_claim(ClaimStatus.INSUFFICIENT_EVIDENCE, evidence_ids=[])],
    )

    result = report_summary(report)

    assert result["needs_review"] is True
    assert result["confidence"] == 86
    assert result["compliance"] == [
        "Claim ‘Up to 30 hours with ANC off.’ is not backed by company data: "
        "No evidence establishes this claim."
    ]
    five_checks = [
        {"name": "claim: unsupported", "passed": False, "reason": "No evidence."},
        *[{"name": f"check-{index}", "passed": True, "reason": None} for index in range(4)],
    ]
    assert _confidence(five_checks) == 80


def test_contradicted_claim_is_a_plain_language_compliance_item():
    claim = _claim(
        ClaimStatus.CONTRADICTED,
        text="AeroBeat AB-01 headphones are completely waterproof.",
    ).model_copy(update={"explanation": "The product page says it is not waterproof."})
    issue = Issue(
        id="issue-1",
        claim_id=claim.id,
        category=IssueCategory.AD_LANDING_PAGE_CONTRADICTION,
        severity=Severity.HIGH,
        explanation="The product page says it is not waterproof.",
        action=IssueAction.FIX,
        policy_reference="landing_page_consistency",
    )
    result = report_summary(
        _report(
            Decision.FIX_REQUIRED,
            claims=[claim],
            evidence=[_evidence(excerpt="It is not waterproof and should not be submerged.")],
            issues=[issue],
        )
    )

    assert result["compliance"] == [
        "Claim ‘AeroBeat AB-01 headphones are completely waterproof.’ is contradicted: "
        "The product page says it is not waterproof."
    ]
    assert result["claims"] == []


def test_report_summary_escapes_no_ascii_double_quotes():
    claim = _claim(
        ClaimStatus.CONTRADICTED,
        text='AeroBeat calls this "waterproof".',
    ).model_copy(update={"explanation": 'The product page says "not waterproof".'})
    report = _report(
        Decision.FIX_REQUIRED,
        ad_copy='AeroBeat says "waterproof".',
        claims=[claim],
    )

    result = report_summary(report)
    serialized = json.dumps(result, ensure_ascii=False)

    assert '\\"' not in serialized
    assert result["ad"]["ad_copy"] == "AeroBeat says ’waterproof’."
    assert result["compliance"] == [
        "Claim ‘AeroBeat calls this ’waterproof’.’ is contradicted: "
        "The product page says ’not waterproof’."
    ]


def test_audit_ad_uses_landing_page_evidence_url():
    landing_page = _evidence(excerpt="Product page evidence.").model_copy(
        update={
            "source_type": "landing_page",
            "source_url": "https://aerobeat.example/landing",
        }
    )
    result = report_summary(_report(evidence=[landing_page]))

    assert result["ad"]["final_url"] == "https://aerobeat.example/landing"


def test_blocked_verdict_uses_first_active_policy_violation():
    report = _report(
        Decision.BLOCK,
        policies=[
            _policy_check(
                predicate_established=True,
                finding="A policy violation was established.",
            )
        ],
    )

    result = report_summary(report)

    assert result["needs_review"] is True
    assert result["summary"] == f"Blocked: {POLICY_TITLE}."
    assert result["compliance"] == [f"Breaks {POLICY_TITLE}"]


def test_minors_processing_error_prevents_ready_and_names_scope_failure():
    minors_error = TypedError(
        code=TypedErrorCode.UNSUPPORTED_CONTEXT,
        message=(
            "This ad targets minors, which is outside the supported adult-audience scope; "
            "a human review is required."
        ),
    )
    result = report_summary(
        _report(
            Decision.PASS,
            audit_errors=[minors_error],
            report_errors=[minors_error],
        )
    )

    assert result["needs_review"] is True
    assert result["compliance"] == [minors_error.message]


def test_report_processing_error_prevents_ready_even_when_audit_passes():
    error = TypedError(
        code=TypedErrorCode.INTERNAL,
        message="A workflow processing error occurred.",
    )
    result = report_summary(_report(Decision.PASS, report_errors=[error]))

    assert result["needs_review"] is True
    assert result["compliance"] == [error.message]


def test_generation_failure_has_scored_shape_and_zero_confidence():
    rendered = render_generation_failure("Generate an ad for AB-01", "Model unavailable.")
    result = json.loads(rendered.removeprefix("```json\n").removesuffix("\n```"))

    assert result["needs_review"] is True
    assert result["confidence"] == 0
    assert result["summary"] == "Needs review: Model unavailable."
    assert result["ad"] is None
    assert result["compliance"] == ["Model unavailable."]
    assert list(result) == [
        "audit_id",
        "needs_review",
        "confidence",
        "summary",
        "ad",
        "compliance",
        "claims",
    ]


def test_claim_quote_is_truncated_to_200_characters_and_shape_key_order():
    excerpt = "x" * 240
    result = report_summary(
        _report(
            claims=[_claim()],
            evidence=[_evidence(excerpt=excerpt)],
            with_generation=True,
        )
    )

    assert len(result["claims"][0]["quote"]) == 200
    assert result["claims"][0]["quote"].endswith("…")
    assert list(result) == [
        "audit_id",
        "needs_review",
        "confidence",
        "summary",
        "ad",
        "compliance",
        "claims",
    ]
