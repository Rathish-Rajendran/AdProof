from __future__ import annotations

import uuid
from dataclasses import dataclass

from adproof.domain.models import (
    ClaimSource,
    CreativeCandidate,
    Decision,
    InspectionStatus,
    Phase,
    RepairRequest,
    RepairResult,
    TypedError,
    VerificationRequest,
    VerificationResult,
)
from adproof.model_client import ModelClient, ModelClientError
from adproof.remediator.remediator import remediate_copy
from adproof.verifier.verifier import VerificationDependencies, verify_campaign


@dataclass
class VerificationCycle:
    original: VerificationResult
    repair: RepairResult | None
    revised_candidate: CreativeCandidate | None
    revised: VerificationResult | None
    selected_candidate_id: str
    final_decision: Decision
    repair_verified: bool
    errors: list[TypedError]


async def verify_with_one_repair(
    candidate: CreativeCandidate,
    request: VerificationRequest,
    *,
    verification: VerificationDependencies,
    model: ModelClient,
    gateway=None,
    recheck_image_status: InspectionStatus | None = None,
    image_text_replacement: bool = False,
) -> VerificationCycle:
    original = await (
        gateway.verify(request) if gateway else verify_campaign(request, verification)
    )
    if isinstance(original, TypedError):
        raise ModelClientError(original)

    repair = None
    revised_candidate = None
    revised = None
    selected_candidate_id = candidate.candidate_id
    final_decision = original.decision
    repair_verified = False
    errors = list(original.errors)
    if original.decision == Decision.FIX_REQUIRED and original.issues:
        repaired_id = f"candidate-{uuid.uuid4().hex[:12]}"
        repair_request = RepairRequest(
            audit_id=request.audit_id,
            request_id=uuid.uuid4().hex,
            campaign_id=candidate.campaign_id,
            original_candidate_id=candidate.candidate_id,
            candidate_id=repaired_id,
            ad_copy=candidate.ad_copy,
            issues=original.issues,
            claims=[
                claim.model_copy(update={"source": ClaimSource.AD_TEXT})
                if image_text_replacement and claim.source == ClaimSource.IMAGE
                else claim
                for claim in original.claims
            ],
            evidence=original.evidence,
            deadline=request.deadline,
        )
        repair = (
            await gateway.repair(repair_request)
            if gateway
            else await remediate_copy(
                audit_id=request.audit_id,
                candidate_id=candidate.candidate_id,
                ad_copy=candidate.ad_copy,
                issues=original.issues,
                claims=repair_request.claims,
                evidence=original.evidence,
                model=model,
                deadline=request.deadline,
            )
        )
        if isinstance(repair, TypedError):
            raise ModelClientError(repair)
        errors.extend(repair.errors)
        revised_candidate = candidate.model_copy(
            update={
                "candidate_id": repaired_id,
                "creative_version": candidate.creative_version + 1,
                "phase": Phase.REPAIRED,
                "ad_copy": repair.repaired_copy,
            }
        )
        request_updates = {
            "candidate_id": repaired_id,
            "creative_version": candidate.creative_version + 1,
            "phase": Phase.REPAIRED,
            "ad_copy": repair.repaired_copy,
            "request_id": uuid.uuid4().hex,
        }
        if recheck_image_status is not None:
            request_updates["image_inspection_status"] = recheck_image_status
            if recheck_image_status == InspectionStatus.NOT_APPLICABLE:
                request_updates["image_observations"] = []
        revised_request = request.model_copy(update=request_updates)
        revised = await (
            gateway.verify(revised_request)
            if gateway
            else verify_campaign(revised_request, verification)
        )
        if isinstance(revised, TypedError):
            raise ModelClientError(revised)
        errors.extend(revised.errors)
        selected_candidate_id = repaired_id
        final_decision = revised.decision
        repair_verified = (
            revised.decision == Decision.PASS
            and repair.repaired_copy != candidate.ad_copy
            and not repair.errors
        )

    return VerificationCycle(
        original=original,
        repair=repair,
        revised_candidate=revised_candidate,
        revised=revised,
        selected_candidate_id=selected_candidate_id,
        final_decision=final_decision,
        repair_verified=repair_verified,
        errors=errors,
    )
