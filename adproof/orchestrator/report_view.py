"""Turn an AuditReport into a small JSON result for chat and API callers.

The result follows the workflow: original check -> fix -> independent re-check -> final verdict.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, TypedDict
from uuid import uuid4

from adproof.domain.models import (
    AuditReport,
    ClaimStatus,
    Decision,
    PolicyReviewStatus,
    VerificationResult,
)
from adproof.generator.generator import parse_generation_request

ROOT = Path(__file__).resolve().parents[2]
READY_THRESHOLD = 95


class Check(TypedDict):
    name: str
    passed: bool
    reason: str | None


def score_checks(report: AuditReport) -> list[Check]:
    """Evaluate deterministic checks against the final audit in a report."""
    audit = _final_audit(report)
    if audit is None:
        reason = report.errors[0].message if report.errors else "Verification did not finish."
        return [{"name": "verification", "passed": False, "reason": reason}]

    checks: list[Check] = []
    for claim in audit.claims:
        passed = claim.status == ClaimStatus.SUPPORTED and bool(claim.evidence_ids)
        checks.append(
            {
                "name": f"claim: {claim.claim}",
                "passed": passed,
                "reason": None if passed else claim.explanation,
            }
        )

    for policy in audit.policy_checks:
        if policy.review_status != PolicyReviewStatus.ACTIVE:
            continue
        passed = policy.checked and not policy.predicate_established
        reason = None
        if not passed:
            reason = policy.finding or (
                "The policy violation predicate was established."
                if policy.predicate_established
                else "The active policy rule was not checked."
            )
        checks.append(
            {
                "name": f"policy: {_policy_title(policy.rule_id)}",
                "passed": passed,
                "reason": reason,
            }
        )

    for field in ("ad_text", "landing_page", "image", "platform_policy"):
        coverage = getattr(audit.coverage, field)
        checks.append(
            {
                "name": f"coverage: {field}",
                "passed": coverage.status.value in {"CHECKED", "NOT_APPLICABLE"},
                "reason": coverage.reason,
            }
        )

    checks.append(
        {
            "name": "no_unresolved_issues",
            "passed": not audit.issues,
            "reason": None if not audit.issues else audit.issues[0].explanation,
        }
    )
    errors = [*audit.errors, *report.errors]
    checks.append(
        {
            "name": "no_processing_errors",
            "passed": not errors,
            "reason": None if not errors else errors[0].message,
        }
    )
    return checks


def report_summary(report: AuditReport) -> dict[str, Any]:
    """Build the deterministic scored JSON report."""
    final_audit = _final_audit(report)
    original = _step(report.original_audit)
    checks = score_checks(report)
    confidence = _confidence(checks)
    checks_failed = [
        {"check": check["name"], "reason": check["reason"]}
        for check in checks
        if not check["passed"]
    ]
    verdict = _verdict(report.final_decision, confidence, checks)
    notes = _notes(report)
    summary: dict[str, Any] = {
        "audit_id": report.audit_id,
        "verdict": verdict,
        "confidence": confidence,
        "summary": _summary_text(
            verdict,
            checks,
            notes,
            final_audit,
        ),
    }
    if report.generation_request is not None:
        request = dict(report.generation_request)
        if "product_query" in request:
            request["prompt"] = request.pop("product_query")
        summary["request"] = request
    if report.generated_ad is not None:
        summary["generated_ad"] = report.generated_ad
    summary["original_check"] = original
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
    summary["claims"] = _claims_summary(final_audit)
    summary["compliance"] = _compliance_summary(final_audit)
    summary["checks_failed"] = checks_failed
    if notes:
        summary["notes"] = notes
    return summary


def render_report(report: AuditReport) -> str:
    """The chat reply: the result as one pretty-printed JSON block."""
    return "```json\n" + json.dumps(report_summary(report), indent=2, ensure_ascii=False) + "\n```"


def render_generation_failure(
    prompt: str,
    message: str,
    *,
    audit_id: str | None = None,
    attempt_violations: list[list[str]] | None = None,
) -> str:
    notes = [message]
    notes.extend(
        f"Attempt {attempt}: {violation}"
        for attempt, violations in enumerate(attempt_violations or [], start=1)
        for violation in violations
    )
    checks: list[Check] = [{"name": "verification", "passed": False, "reason": message}]
    checks_failed = [{"check": "verification", "reason": message}]
    summary = {
        "audit_id": audit_id or uuid4().hex,
        "verdict": "NEEDS_HUMAN_APPROVAL",
        "confidence": 0,
        "summary": _summary_text(
            "NEEDS_HUMAN_APPROVAL",
            checks,
            notes,
            None,
        ),
        "request": parse_generation_request(prompt).model_dump(mode="json"),
        "original_check": {"decision": None, "issues": []},
        "final": {
            "decision": "HUMAN_REVIEW",
            "ad_copy": None,
            "repair_verified": False,
        },
        "claims": [],
        "compliance": [],
        "checks_failed": checks_failed,
    }
    if notes:
        summary["notes"] = notes
    return "```json\n" + json.dumps(summary, indent=2, ensure_ascii=False) + "\n```"


def _final_audit(report: AuditReport) -> VerificationResult | None:
    return report.revised_audit if report.revised_audit is not None else report.original_audit


@lru_cache(maxsize=1)
def _policy_titles() -> dict[str, str]:
    try:
        catalog = json.loads(
            (ROOT / "data" / "policies" / "catalog.json").read_text(encoding="utf-8")
        )
        return {rule["rule_id"]: rule["title"] for rule in catalog["rules"]}
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return {}


def _policy_title(rule_id: str) -> str:
    return _policy_titles().get(rule_id, rule_id)


def _verdict(decision: Decision, confidence: int, checks: list[Check]) -> str:
    if decision == Decision.BLOCK:
        return "BLOCKED"
    if (
        decision == Decision.PASS
        and confidence >= READY_THRESHOLD
        and all(check["passed"] for check in checks)
    ):
        return "READY"
    return "NEEDS_HUMAN_APPROVAL"


def _confidence(checks: list[Check]) -> int:
    return round(100 * sum(check["passed"] for check in checks) / len(checks)) if checks else 0


def _notes(report: AuditReport) -> list[str]:
    candidates = [error.message for error in report.errors]
    if report.coverage is not None:
        candidates.extend(
            item["reason"]
            for item in report.coverage.model_dump().values()
            if item["status"] not in {"CHECKED", "NOT_APPLICABLE"} and item["reason"]
        )
    return list(dict.fromkeys(candidates))


def _summary_text(
    verdict: str,
    checks: list[Check],
    notes: list[str],
    audit: VerificationResult | None,
) -> str:
    if verdict == "READY":
        claims = audit.claims if audit else []
        evidence_by_id = {item.id: item for item in audit.evidence} if audit else {}
        documents = list(
            dict.fromkeys(
                document
                for claim in claims
                for evidence_id in claim.evidence_ids
                if (evidence := evidence_by_id.get(evidence_id)) is not None
                if (document := evidence.document_id or evidence.source_url)
            )
        )
        policy_count = (
            sum(check.review_status == PolicyReviewStatus.ACTIVE for check in audit.policy_checks)
            if audit
            else 0
        )
        return (
            f"All {len(claims)} claims are backed by {', '.join(documents)}; "
            f"{policy_count} policy rules checked, none broken."
        )
    if verdict == "BLOCKED":
        violation = None
        if audit is not None:
            violation = next(
                (
                    _policy_title(policy.rule_id)
                    for policy in audit.policy_checks
                    if policy.review_status == PolicyReviewStatus.ACTIVE
                    and policy.predicate_established
                ),
                None,
            )
        return f"Blocked: {violation or 'a policy rule'}."
    failed = [check for check in checks if not check["passed"]]
    if not checks:
        return notes[0] if notes else "No checks were available."
    if not failed:
        return "No checks failed, but human approval is needed."
    first = failed[0]
    reason = first["reason"] or "No reason supplied."
    return (
        f"{len(failed)} of {len(checks)} checks failed "
        f"({first['name']}: {reason}). Human approval needed."
    )


def _claims_summary(audit: VerificationResult | None) -> list[dict[str, Any]]:
    if audit is None:
        return []
    evidence_by_id = {item.id: item for item in audit.evidence}
    claims = []
    for claim in audit.claims:
        evidence = evidence_by_id.get(claim.evidence_ids[0]) if claim.evidence_ids else None
        excerpt = evidence.excerpt if evidence is not None else None
        if excerpt is not None and len(excerpt) > 200:
            excerpt = excerpt[:199] + "…"
        claims.append(
            {
                "claim": claim.claim,
                "result": claim.status.value,
                "source": (
                    evidence.locator or evidence.document_id or evidence.source_url
                    if evidence is not None
                    else None
                ),
                "quote": excerpt,
            }
        )
    return claims


def _compliance_summary(audit: VerificationResult | None) -> list[dict[str, str]]:
    if audit is None:
        return []
    compliance = []
    for policy in audit.policy_checks:
        if policy.review_status != PolicyReviewStatus.ACTIVE:
            continue
        result = (
            "VIOLATION"
            if policy.predicate_established
            else "OK"
            if policy.checked
            else "NOT_CHECKED"
        )
        compliance.append(
            {
                "policy": _policy_title(policy.rule_id),
                "rule_id": policy.rule_id,
                "result": result,
            }
        )
    return compliance


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
