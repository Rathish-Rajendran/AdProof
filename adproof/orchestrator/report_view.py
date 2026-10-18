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
    CreativeCandidate,
    Decision,
    Evidence,
    PolicyReviewStatus,
    VerificationResult,
)
from adproof.rag.chunker import CorpusChunk, CorpusDocument, chunk_document, load_corpus

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
    """Build the compact deterministic JSON report."""
    final_audit = _final_audit(report)
    checks = score_checks(report)
    confidence = _confidence(checks)
    verdict = _verdict(report.final_decision, confidence, checks)
    compliance = _compliance_summary(checks, final_audit)
    return {
        "audit_id": report.audit_id,
        "needs_review": verdict != "READY",
        "confidence": confidence,
        "summary": _summary_text(verdict, compliance, report, final_audit),
        "ad": _ad_summary(report),
        "compliance": compliance,
        "claims": _claims_summary(final_audit),
    }


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
    del prompt
    compliance = list(
        dict.fromkeys(
            [message, *(violation for attempt in attempt_violations or [] for violation in attempt)]
        )
    )
    summary = {
        "audit_id": audit_id or uuid4().hex,
        "needs_review": True,
        "confidence": 0,
        "summary": _review_summary(compliance),
        "ad": None,
        "compliance": compliance,
        "claims": [],
    }
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


def _summary_text(
    verdict: str,
    compliance: str | list[str],
    report: AuditReport,
    audit: VerificationResult | None,
) -> str:
    if verdict == "READY":
        if (
            report.check_input_type == "image"
            and report.repair_proposal is not None
            and report.repair_verified
        ):
            return "Fixed once and re-checked: replace the image text with fixed_text."
        claims = audit.claims if audit is not None else []
        policy_count = (
            sum(
                policy.review_status == PolicyReviewStatus.ACTIVE
                and policy.checked
                and not policy.predicate_established
                for policy in audit.policy_checks
            )
            if audit is not None
            else 0
        )
        backing = (
            "company data"
            if (
                report.generation_request is not None
                or report.generated_ad is not None
                or report.check_input_type is not None
            )
            else "the landing page"
        )
        platform = _platform_label(_platform(report))
        repair_prefix = ""
        if report.repair_proposal is not None:
            original_issue_count = len(report.original_audit.issues) if report.original_audit else 0
            repair_prefix = (
                f"The first draft had {original_issue_count} issues; "
                "it was fixed once and re-checked. "
            )
        return (
            f"{repair_prefix}Ready to run: all {len(claims)} claims are backed by {backing}; "
            f"{policy_count} {platform} rules passed."
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
        if violation is None and isinstance(compliance, list) and compliance:
            violation = compliance[0].removeprefix("Breaks ")
        return f"Blocked: {violation or 'policy violation'}."
    return _review_summary(compliance)


def _review_summary(compliance: str | list[str]) -> str:
    items = compliance if isinstance(compliance, list) else []
    if not items:
        return "Needs review: the final decision requires review"
    suffix = f" ({len(items) - 1} more)" if len(items) > 1 else ""
    return f"Needs review: {items[0]}{suffix}"


def _platform(report: AuditReport) -> str | None:
    if report.generation_request is not None:
        platform = report.generation_request.get("platform")
        if platform:
            return str(platform)
    return report.original_candidate.context.platform


def _platform_label(platform: str | None) -> str:
    return {
        "google_ads": "Google Ads",
        "meta_ads": "Meta Ads",
    }.get(platform or "", platform or "Ads")


def _ad_summary(report: AuditReport) -> dict[str, Any] | None:
    if report.check_input_type == "image":
        return {
            "type": "image",
            "detected_text": report.image_detected_text or "",
            "fixed_text": (
                report.repair_proposal.repaired_copy
                if report.repair_proposal is not None
                and report.repair_proposal.repaired_copy != report.original_candidate.ad_copy
                else None
            ),
        }
    if report.check_input_type == "text":
        return {"type": "text", "ad_copy": _final_copy(report)}
    is_generation = report.generation_request is not None or report.generated_ad is not None
    if is_generation:
        if report.generated_ad is None or _final_audit(report) is None:
            return None
        platform = _platform(report)
        if report.repair_proposal is not None:
            final_candidate = _final_candidate(report)
            final_url = report.generated_ad.get("final_url") or (
                final_candidate.asset_ref if final_candidate is not None else None
            )
            return {
                "platform": platform,
                "ad_copy": report.repair_proposal.repaired_copy,
                "final_url": final_url,
            }
        ad = {key: value for key, value in report.generated_ad.items() if key != "sources"}
        return {"platform": platform, **ad}

    final_candidate = _final_candidate(report)
    final_audit = _final_audit(report)
    return {
        "ad_copy": _final_copy(report),
        "final_url": _landing_page_url(final_audit, final_candidate),
    }


def _final_candidate(report: AuditReport) -> CreativeCandidate:
    if (
        report.revised_candidate is not None
        and report.selected_candidate_id == report.revised_candidate.candidate_id
    ):
        return report.revised_candidate
    return report.original_candidate


def _landing_page_url(
    audit: VerificationResult | None,
    candidate: CreativeCandidate,
) -> str:
    if audit is not None:
        landing_page = next(
            (item for item in audit.evidence if item.source_type == "landing_page"),
            None,
        )
        if landing_page is not None:
            return landing_page.source_url
    return candidate.asset_ref


def _compliance_summary(
    checks: list[Check],
    audit: VerificationResult | None,
) -> str | list[str]:
    failed_checks = [check for check in checks if not check["passed"]]
    if not failed_checks:
        return "OK"

    failed_claim_ids: set[str] = set()
    messages: list[str] = []
    for check in failed_checks:
        name = check["name"]
        reason = check["reason"]
        message: str | None
        if name.startswith("claim: "):
            claim_text = name.removeprefix("claim: ")
            claim = (
                next(
                    (item for item in audit.claims if item.claim == claim_text),
                    None,
                )
                if audit is not None
                else None
            )
            if claim is None:
                message = reason or "A claim could not be verified."
            else:
                failed_claim_ids.add(claim.id)
                state = (
                    "contradicted"
                    if claim.status == ClaimStatus.CONTRADICTED
                    else "not backed by company data"
                )
                message = f'Claim "{claim.claim}" is {state}: {claim.explanation}'
        elif name.startswith("policy: "):
            message = f"Breaks {name.removeprefix('policy: ')}"
        elif name == "no_unresolved_issues":
            first_issue = audit.issues[0] if audit is not None and audit.issues else None
            message = (
                None
                if first_issue is not None and first_issue.claim_id in failed_claim_ids
                else reason or "An unresolved issue remains."
            )
        elif name == "no_processing_errors":
            message = reason or "Processing did not finish."
        elif name.startswith("coverage: "):
            message = reason or "Coverage was not completed."
        elif name == "verification":
            message = reason or "Verification did not finish."
        else:
            message = reason or "The check did not pass."
        if message and message not in messages:
            messages.append(message)
    return messages or ["The final audit needs review."]


@lru_cache(maxsize=1)
def _corpus_documents() -> dict[str, tuple[CorpusDocument, list[CorpusChunk]]]:
    documents = load_corpus(ROOT / "data" / "corpus" / "aerobeat")
    return {document.doc_id: (document, chunk_document(document)) for document in documents}


def _corpus_source(evidence: Evidence) -> str:
    entry = _corpus_documents().get(evidence.document_id or "")
    if entry is None:
        return evidence.source_url
    document, chunks = entry
    matching_chunk = next(
        (chunk for chunk in chunks if evidence.excerpt and evidence.excerpt in chunk.text),
        None,
    )
    if matching_chunk is None:
        return document.title
    heading = matching_chunk.heading
    if heading.startswith(document.title):
        heading = heading[len(document.title) :].strip(" /›—-")
    parts = heading.split(" / ")
    if len(parts) > 1:
        heading = " / ".join(parts[1:])
    return f"{document.title} › {heading}" if heading else document.title


def _claims_summary(audit: VerificationResult | None) -> list[dict[str, Any]]:
    if audit is None:
        return []
    evidence_by_id = {item.id: item for item in audit.evidence}
    claims = []
    for claim in audit.claims:
        if claim.status != ClaimStatus.SUPPORTED:
            continue
        evidence = evidence_by_id.get(claim.evidence_ids[0]) if claim.evidence_ids else None
        if evidence is None:
            continue
        excerpt = evidence.excerpt
        if len(excerpt) > 200:
            excerpt = excerpt[:199] + "…"
        source = (
            _corpus_source(evidence)
            if evidence.source_type == "company_corpus"
            else evidence.source_url
        )
        claims.append(
            {
                "claim": claim.claim,
                "quote": excerpt,
                "source": source,
            }
        )
    return claims


def _final_copy(report: AuditReport) -> str:
    if (
        report.revised_candidate
        and report.selected_candidate_id == report.revised_candidate.candidate_id
    ):
        return report.revised_candidate.ad_copy
    return report.original_candidate.ad_copy
