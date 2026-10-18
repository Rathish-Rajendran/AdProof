"""Turn an AuditReport into a small JSON result for chat and API callers.

The result follows the workflow: original check -> fix -> independent re-check -> final verdict.
"""

from __future__ import annotations

import json
from typing import Any

from adproof.domain.models import AuditReport, VerificationResult


def report_summary(report: AuditReport) -> dict[str, Any]:
    """The API-style result, one entry per workflow step."""
    original = _step(report.original_audit)
    summary: dict[str, Any] = {"audit_id": report.audit_id, "original_check": original}
    if report.repair_proposal:
        recheck = _step(report.revised_audit)
        recheck["changed_decision"] = (
            recheck["decision"] is not None and recheck["decision"] != original["decision"]
        )
        summary["fix"] = {"ad_copy": report.repair_proposal.repaired_copy}
        if report.repair_proposal.image_edit_instructions:
            summary["fix"]["image_changes"] = report.repair_proposal.image_edit_instructions
        summary["recheck"] = recheck
    summary["final"] = {
        "decision": report.final_decision.value,
        "ad_copy": _final_copy(report),
        "repair_verified": report.repair_verified,
    }
    notes = list(dict.fromkeys(error.message for error in report.errors))
    if notes:
        summary["notes"] = notes
    return summary


def render_report(report: AuditReport) -> str:
    """The chat reply: the result as one pretty-printed JSON block."""
    return "```json\n" + json.dumps(report_summary(report), indent=2, ensure_ascii=False) + "\n```"


def _step(audit: VerificationResult | None) -> dict[str, Any]:
    if audit is None:
        return {"decision": None, "issues": []}
    issues = [
        {"claim": claim.claim, "status": claim.status.value, "why": claim.explanation}
        for claim in audit.claims
        if claim.status.value != "SUPPORTED"
    ]
    claim_ids = {claim.id for claim in audit.claims}
    issues += [
        {"claim": None, "status": issue.category.value, "why": issue.explanation}
        for issue in audit.issues
        if issue.claim_id not in claim_ids
    ]
    return {"decision": audit.decision.value, "issues": issues}


def _final_copy(report: AuditReport) -> str:
    if (
        report.revised_candidate
        and report.selected_candidate_id == report.revised_candidate.candidate_id
    ):
        return report.revised_candidate.ad_copy
    return report.original_candidate.ad_copy
