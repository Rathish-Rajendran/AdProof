from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from adproof.domain.models import (
    CampaignContext,
    Claim,
    CoverageItem,
    CoverageStatus,
    Issue,
    IssueAction,
    IssueCategory,
    PolicyCheck,
    PolicyEnforcement,
    PolicyReviewStatus,
    Severity,
)


class PolicyRule(BaseModel):
    model_config = ConfigDict(extra="allow")
    rule_id: str
    title: str
    source_url: str
    section: str | None = None
    excerpt: str | None = None
    retrieved_at: datetime | None = None
    content_sha256: str | None = None
    applicability: dict[str, list[str]] = Field(default_factory=dict)
    required_facts: list[str] = Field(default_factory=list)
    violation_predicate: dict[str, Any] | None = None
    issue_category: IssueCategory
    issue_category_overrides: dict[str, IssueCategory] = Field(default_factory=dict)
    default_action: IssueAction
    enforcement: PolicyEnforcement
    review_status: PolicyReviewStatus
    review: dict[str, Any] | None = None


class PolicyPack(BaseModel):
    model_config = ConfigDict(extra="allow")
    pack_id: str
    version: str
    catalog_version: str | None = None
    platform: str
    jurisdiction: str
    language: str
    category: str
    audience: str | None = None
    freshness_days: int = Field(gt=0)
    required_checks: list[str] = Field(default_factory=list)
    required_rule_ids: list[str] = Field(default_factory=list)
    optional_rule_ids: list[str] = Field(default_factory=list)


class PolicyCatalogError(ValueError):
    pass


class PolicyEngine:
    def __init__(self, catalog: dict[str, Any], pack: dict[str, Any]):
        try:
            self.version = str(catalog["version"])
            self.pack = PolicyPack.model_validate(pack)
            self.rules = {
                parsed.rule_id: parsed
                for raw in catalog["rules"]
                if (parsed := PolicyRule.model_validate(raw))
            }
        except (KeyError, TypeError, ValidationError) as exc:
            raise PolicyCatalogError("policy catalog or pack has an invalid shape") from exc
        for rule in self.rules.values():
            if rule.review_status == PolicyReviewStatus.ACTIVE:
                if not rule.excerpt or not rule.content_sha256 or not rule.retrieved_at:
                    raise PolicyCatalogError(f"ACTIVE rule {rule.rule_id} lacks source provenance")
                if not rule.review or any(
                    not rule.review.get(key) for key in ("kind", "reviewer", "role", "reviewed_at")
                ):
                    raise PolicyCatalogError(f"ACTIVE rule {rule.rule_id} lacks review provenance")

    @classmethod
    def from_files(cls, catalog_path: Path, pack_path: Path) -> PolicyEngine:
        return cls(
            json.loads(catalog_path.read_text(encoding="utf-8")),
            json.loads(pack_path.read_text(encoding="utf-8")),
        )

    def evaluate(
        self,
        *,
        context: CampaignContext,
        claims: list[Claim],
        valid_evidence_ids: set[str],
        now: datetime | None = None,
    ) -> tuple[list[PolicyCheck], CoverageItem, list[Issue]]:
        now = now or datetime.now(UTC)
        checks: list[PolicyCheck] = []
        issues: list[Issue] = []
        required_ids = self.pack.required_rule_ids
        required_complete = True
        for rule_id in (*required_ids, *self.pack.optional_rule_ids):
            rule = self.rules.get(rule_id)
            if rule is None:
                if rule_id in required_ids:
                    required_complete = False
                continue
            if rule.review_status != PolicyReviewStatus.ACTIVE:
                if rule_id in required_ids:
                    required_complete = False
                checks.append(
                    PolicyCheck(
                        rule_id=rule_id,
                        applicable=False,
                        review_status=rule.review_status,
                        enforcement=rule.enforcement,
                        checked=False,
                        finding="Rule is not ACTIVE and was not evaluated.",
                    )
                )
                continue
            if rule_id in required_ids:
                stale = not rule.retrieved_at or now - rule.retrieved_at > timedelta(
                    days=self.pack.freshness_days
                )
                if stale:
                    required_complete = False
            applicable_context = self._context_applicable(rule, context)
            applicable_claims = [
                claim
                for claim in claims
                if applicable_context and self._claim_applicable(rule, claim)
            ]
            predicates = []
            for claim in applicable_claims:
                predicate = rule.violation_predicate or {}
                kind = predicate.get("kind")
                expected = predicate.get("equals")
                actual = (
                    claim.landing_page_consistency.value
                    if kind == "claim_landing_page_consistency"
                    else claim.status.value
                    if kind == "claim_status"
                    else None
                )
                valid_evidence = bool(set(claim.evidence_ids) & valid_evidence_ids)
                if actual == expected and (
                    not predicate.get("requires_valid_evidence") or valid_evidence
                ):
                    predicates.append(claim)
            checks.append(
                PolicyCheck(
                    rule_id=rule_id,
                    applicable=bool(applicable_context and applicable_claims),
                    review_status=rule.review_status,
                    enforcement=rule.enforcement,
                    checked=bool(applicable_context),
                    finding="Predicate established." if predicates else None,
                    predicate_established=bool(predicates),
                )
            )
            for claim in predicates:
                category = rule.issue_category_overrides.get(
                    claim.claim_type.value, rule.issue_category
                )
                issues.append(
                    Issue(
                        id=f"policy-{rule.rule_id}-{claim.id}",
                        claim_id=claim.id,
                        category=category,
                        severity=Severity.HIGH,
                        explanation=f"Applicable reviewed rule predicate {rule.rule_id} was established.",
                        suggested_fix="Correct or qualify the contradicted claim.",
                        action=rule.default_action,
                        policy_reference=rule.rule_id,
                    )
                )
        status = CoverageStatus.CHECKED if required_complete else CoverageStatus.PARTIAL
        reason = None if required_complete else "A required rule is missing, stale, or not ACTIVE."
        return checks, CoverageItem(status=status, reason=reason), issues

    def _context_applicable(self, rule: PolicyRule, context: CampaignContext) -> bool:
        values = {
            "platforms": context.platform,
            "jurisdictions": context.jurisdiction,
            "languages": context.language,
            "categories": context.product_category,
        }
        return all(
            not allowed or values[key] in allowed
            for key, allowed in rule.applicability.items()
            if key in values
        )

    @staticmethod
    def _claim_applicable(rule: PolicyRule, claim: Claim) -> bool:
        applicability = rule.applicability
        claim_types = applicability.get("claim_types", [])
        sources = applicability.get("sources", [])
        return (not claim_types or claim.claim_type.value in claim_types) and (
            not sources or claim.source.value in sources
        )
