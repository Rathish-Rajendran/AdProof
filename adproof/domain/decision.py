from __future__ import annotations

from collections.abc import Iterable

from adproof.domain.models import (
    Coverage,
    CoverageStatus,
    Decision,
    Issue,
    IssueAction,
    PolicyCheck,
    PolicyEnforcement,
    PolicyReviewStatus,
    ReportSelection,
    TypedError,
    TypedErrorCode,
    VerificationResult,
    WorkflowStatus,
)


def decide(
    *,
    issues: Iterable[Issue],
    coverage_complete: bool,
    material_uncertainty: bool = False,
    processing_failed: bool = False,
    errors: Iterable[TypedError] = (),
    policy_checks: Iterable[PolicyCheck] = (),
) -> Decision:
    checks = list(policy_checks)
    established_block = any(
        check.applicable
        and check.checked
        and check.review_status == PolicyReviewStatus.ACTIVE
        and check.enforcement == PolicyEnforcement.BLOCK
        and check.predicate_established
        for check in checks
    )
    if established_block:
        return Decision.BLOCK
    if (
        material_uncertainty
        or processing_failed
        or not coverage_complete
        or any(
            error.code in {TypedErrorCode.INVALID_EVIDENCE, TypedErrorCode.UNSUPPORTED_CONTEXT}
            for error in errors
        )
    ):
        return Decision.HUMAN_REVIEW
    issue_list = list(issues)
    if any(issue.action == IssueAction.REVIEW for issue in issue_list):
        return Decision.HUMAN_REVIEW
    if issue_list:
        return Decision.FIX_REQUIRED
    return Decision.PASS


def coverage_is_complete(coverage: Coverage) -> bool:
    required = (
        coverage.ad_text,
        coverage.landing_page,
        coverage.image,
        coverage.platform_policy,
    )
    return all(
        item.status in {CoverageStatus.CHECKED, CoverageStatus.NOT_APPLICABLE} for item in required
    )


def decide_result(
    result: VerificationResult,
    *,
    material_uncertainty: bool = False,
    processing_failed: bool = False,
) -> Decision:
    return decide(
        issues=result.issues,
        coverage_complete=coverage_is_complete(result.coverage),
        material_uncertainty=material_uncertainty,
        processing_failed=processing_failed or not result.audit_complete,
        errors=result.errors,
        policy_checks=result.policy_checks,
    )


def select_report(
    *,
    original: VerificationResult | None,
    original_candidate_id: str = "original",
    repair_candidate_id: str | None = None,
    revised: VerificationResult | None = None,
    repair_errors: Iterable[TypedError] = (),
) -> ReportSelection:
    errors = list(repair_errors)
    if original is None:
        return ReportSelection(
            selected_candidate_id=original_candidate_id,
            final_decision=Decision.HUMAN_REVIEW,
            final_decision_basis="No valid original audit completed; no candidate is verified.",
            workflow_status=WorkflowStatus.PARTIAL,
            repair_verified=False,
            errors=errors,
        )
    if revised is not None and revised.audit_complete:
        decision = decide_result(revised)
        return ReportSelection(
            selected_candidate_id=revised.candidate_id,
            final_decision=decision,
            final_decision_basis="Selected the independently completed revised-candidate audit.",
            workflow_status=WorkflowStatus.COMPLETED,
            repair_verified=True,
            unresolved_issues=revised.issues,
            coverage=revised.coverage,
            errors=[*original.errors, *revised.errors, *errors],
        )
    if revised is not None:
        decision = decide_result(revised, processing_failed=True)
        return ReportSelection(
            selected_candidate_id=revised.candidate_id,
            final_decision=decision,
            final_decision_basis="Selected the structured but incomplete revised audit; it is not verified.",
            workflow_status=WorkflowStatus.PARTIAL,
            repair_verified=False,
            unresolved_issues=revised.issues,
            coverage=revised.coverage,
            errors=[*original.errors, *revised.errors, *errors],
        )
    return ReportSelection(
        selected_candidate_id=original.candidate_id,
        final_decision=decide_result(original),
        final_decision_basis="The original is the last candidate with a valid audit; any repair remains unverified.",
        workflow_status=WorkflowStatus.PARTIAL
        if repair_candidate_id or errors
        else WorkflowStatus.COMPLETED,
        repair_verified=False,
        unresolved_issues=original.issues,
        coverage=original.coverage,
        errors=[*original.errors, *errors],
    )
