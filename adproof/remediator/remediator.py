from __future__ import annotations

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from adproof.domain.models import (
    Claim,
    Evidence,
    Issue,
    RepairChange,
    RepairResult,
    TypedError,
    TypedErrorCode,
)
from adproof.model_client import ModelClient, ModelClientError

_NUMBER = re.compile(r"\$?\d[\d,]*(?:\.\d+)?%?")
PROMPT_VERSION = "copy-remediation-v1"


class _RepairOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repaired_copy: str = Field(max_length=4096)
    changes: list[RepairChange] = Field(default_factory=list)
    unresolved_issue_ids: list[str] = Field(default_factory=list)


async def remediate_copy(
    *,
    audit_id: str,
    candidate_id: str,
    ad_copy: str,
    issues: list[Issue],
    claims: list[Claim],
    evidence: list[Evidence],
    model: ModelClient,
    deadline: datetime,
    model_version: str = "configured",
) -> RepairResult:
    image_issues = [
        issue
        for issue in issues
        if issue.claim_id
        and any(claim.id == issue.claim_id and claim.source.value == "image" for claim in claims)
    ]
    try:
        response = await model.generate_json(
            [
                "Propose one minimal COPY-ONLY repair for the supplied ad. Use only the validated issues "
                "and source evidence; preserve conditions and qualifiers. Do not add numeric claims unless "
                "they appear in the original copy, validated evidence, or deterministic derivations. "
                "Return each edit with its source issue IDs. Image issues cannot be fixed by copy; list them "
                "as unresolved and provide no verdict.",
                f"AD COPY:\n{ad_copy}",
                f"ISSUES:\n{[issue.model_dump(mode='json') for issue in issues]}",
                f"CLAIMS:\n{[claim.model_dump(mode='json') for claim in claims]}",
                f"EVIDENCE:\n{[item.model_dump(mode='json') for item in evidence]}",
            ],
            _RepairOutput,
            deadline=deadline,
            purpose="copy_remediation",
        )
        proposal = response.data
        model_version = response.model_version
    except ModelClientError as exc:
        return RepairResult(
            audit_id=audit_id,
            original_candidate_id=candidate_id,
            candidate_id=f"candidate-{uuid.uuid4().hex[:12]}",
            repaired_copy=ad_copy,
            model_version=model_version,
            prompt_version=PROMPT_VERSION,
            unresolved_issue_ids=[issue.id for issue in issues],
            image_edit_instructions=[
                f"Edit the image to resolve issue {issue.id}: {issue.explanation}"
                for issue in image_issues
            ],
            errors=[exc.error],
        )
    valid_issue_ids = {issue.id for issue in issues}
    invalid_refs = [
        issue_id
        for change in proposal.changes
        for issue_id in change.issue_ids
        if issue_id not in valid_issue_ids
    ]
    if invalid_refs:
        errors = [
            TypedError(
                code=TypedErrorCode.MODEL_MALFORMED_OUTPUT,
                message="Repair output referenced an unknown issue.",
            )
        ]
        return RepairResult(
            audit_id=audit_id,
            original_candidate_id=candidate_id,
            candidate_id=f"candidate-{uuid.uuid4().hex[:12]}",
            repaired_copy=ad_copy,
            model_version=model_version,
            prompt_version=PROMPT_VERSION,
            unresolved_issue_ids=sorted(valid_issue_ids),
            image_edit_instructions=[
                f"Edit the image to resolve issue {issue.id}: {issue.explanation}"
                for issue in image_issues
            ],
            errors=errors,
        )
    permitted_numbers = set(_NUMBER.findall(ad_copy))
    for item in evidence:
        permitted_numbers.update(_NUMBER.findall(item.excerpt))
    for claim in claims:
        permitted_numbers.update(_NUMBER.findall(str(claim.derivation)))
    invented = set(_NUMBER.findall(proposal.repaired_copy)) - permitted_numbers
    repaired_copy = proposal.repaired_copy
    unresolved = set(proposal.unresolved_issue_ids) | {issue.id for issue in image_issues}
    errors: list[TypedError] = []
    if invented:
        repaired_copy = ad_copy
        unresolved.update(valid_issue_ids)
        errors.append(
            TypedError(
                code=TypedErrorCode.MODEL_MALFORMED_OUTPUT,
                message="Repair introduced numerical claims absent from the original, evidence, or derivations.",
            )
        )
    known_claims = {claim.id: claim for claim in claims}
    for claim in claims:
        qualifiers = claim.conditions.get("qualifiers", [])
        if claim.claim.casefold().find("up to") >= 0:
            qualifiers = [*qualifiers, "up to"]
        condition_terms = claim.conditions.get("condition_terms", {})
        if not isinstance(condition_terms, dict):
            condition_terms = {}
        for key in ("coupon", "subscription", "anc_mode", "noise_cancellation"):
            value = condition_terms.get(key, claim.conditions.get(key))
            if value:
                qualifiers = [
                    *qualifiers,
                    "noise cancellation " + str(value)
                    if key in {"anc_mode", "noise_cancellation"}
                    else key,
                ]
        claim_text = claim.claim.casefold()
        for qualifier in ("noise cancellation off", "noise cancellation on"):
            if qualifier in claim_text:
                qualifiers = [*qualifiers, qualifier]
        if claim.id in {issue.claim_id for issue in issues}:
            if any(
                str(qualifier).casefold() in claim.claim.casefold() for qualifier in qualifiers
            ) and any(
                str(qualifier).casefold() not in repaired_copy.casefold()
                for qualifier in qualifiers
            ):
                for issue in issues:
                    if issue.claim_id == claim.id:
                        unresolved.add(issue.id)
    for issue in issues:
        if issue.claim_id not in known_claims:
            unresolved.add(issue.id)
    return RepairResult(
        audit_id=audit_id,
        original_candidate_id=candidate_id,
        candidate_id=f"candidate-{uuid.uuid4().hex[:12]}",
        repaired_copy=repaired_copy,
        changes=proposal.changes,
        unresolved_issue_ids=sorted(unresolved),
        image_edit_instructions=[
            f"Edit the image to resolve issue {issue.id}: {issue.explanation}"
            for issue in image_issues
        ],
        model_version=model_version,
        prompt_version=PROMPT_VERSION,
        errors=errors,
    )
