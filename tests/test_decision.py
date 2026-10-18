import pytest

from adproof.domain.decision import decide, select_report
from adproof.domain.models import (
    Coverage,
    CoverageItem,
    CoverageStatus,
    Decision,
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


def issue(action: IssueAction = IssueAction.FIX, severity: Severity = Severity.CRITICAL) -> Issue:
    return Issue(
        id="issue-1",
        category=IssueCategory.UNSUPPORTED_OBJECTIVE_CLAIM,
        severity=severity,
        explanation="unsupported",
        action=action,
    )


def coverage(status: CoverageStatus = CoverageStatus.CHECKED) -> Coverage:
    item = CoverageItem(status=status)
    return Coverage(
        ad_text=item,
        landing_page=item,
        supporting_documents=item,
        image=item,
        platform_policy=item,
    )


def audit(
    candidate_id: str,
    *,
    decision: Decision = Decision.PASS,
    complete: bool = True,
    issues: list[Issue] | None = None,
) -> VerificationResult:
    return VerificationResult(
        audit_id="audit",
        campaign_id="campaign",
        candidate_id=candidate_id,
        creative_version=1,
        phase=Phase.ORIGINAL,
        decision=decision,
        audit_complete=complete,
        evidence_scope="bounded test",
        coverage=coverage(CoverageStatus.CHECKED if complete else CoverageStatus.PARTIAL),
        policy_catalog_version="test",
        issues=issues or [],
    )


def test_decision_precedence_requires_applicable_active_blocking_predicate():
    block = PolicyCheck(
        rule_id="block",
        applicable=True,
        review_status=PolicyReviewStatus.ACTIVE,
        enforcement=PolicyEnforcement.BLOCK,
        checked=True,
        predicate_established=True,
    )
    assert decide(issues=[issue()], coverage_complete=True, policy_checks=[block]) == Decision.BLOCK
    assert (
        decide(
            issues=[issue()],
            coverage_complete=True,
            policy_checks=[block.model_copy(update={"review_status": PolicyReviewStatus.DRAFT})],
        )
        == Decision.FIX_REQUIRED
    )
    assert (
        decide(
            issues=[issue()],
            coverage_complete=True,
            policy_checks=[block.model_copy(update={"applicable": False})],
        )
        == Decision.FIX_REQUIRED
    )


def test_severity_never_causes_block_and_uncertainty_precedes_repair():
    assert (
        decide(issues=[issue(severity=Severity.CRITICAL)], coverage_complete=True)
        == Decision.FIX_REQUIRED
    )
    assert decide(issues=[issue()], coverage_complete=False) == Decision.HUMAN_REVIEW
    assert (
        decide(issues=[issue(IssueAction.REVIEW)], coverage_complete=True) == Decision.HUMAN_REVIEW
    )
    assert (
        decide(
            issues=[],
            coverage_complete=True,
            errors=[TypedError(code=TypedErrorCode.INVALID_EVIDENCE, message="bad quote")],
        )
        == Decision.HUMAN_REVIEW
    )
    assert decide(issues=[], coverage_complete=True) == Decision.PASS


@pytest.mark.parametrize(
    ("kwargs", "selected", "decision", "status", "verified"),
    [
        (
            {"original": audit("original")},
            "original",
            Decision.PASS,
            WorkflowStatus.COMPLETED,
            False,
        ),
        (
            {
                "original": audit("original", decision=Decision.FIX_REQUIRED, issues=[issue()]),
                "repair_candidate_id": "revised",
                "revised": audit("revised", decision=Decision.PASS, complete=True),
            },
            "revised",
            Decision.PASS,
            WorkflowStatus.COMPLETED,
            True,
        ),
        (
            {
                "original": audit("original", decision=Decision.FIX_REQUIRED, issues=[issue()]),
                "repair_candidate_id": "revised",
                "revised": audit("revised", complete=False),
            },
            "revised",
            Decision.HUMAN_REVIEW,
            WorkflowStatus.PARTIAL,
            False,
        ),
        (
            {"original": None, "original_candidate_id": "original"},
            "original",
            Decision.HUMAN_REVIEW,
            WorkflowStatus.PARTIAL,
            False,
        ),
    ],
)
def test_report_selection_branches(kwargs, selected, decision, status, verified):
    selection = select_report(**kwargs)
    assert selection.selected_candidate_id == selected
    assert selection.final_decision == decision
    assert selection.workflow_status == status
    assert selection.repair_verified is verified
