from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from adproof.domain.models import (
    AuditReport,
    CampaignContext,
    CreativeCandidate,
    Decision,
    ExecutionMode,
    InspectionStatus,
    Phase,
    RepairRequest,
    TypedError,
    VerificationRequest,
    WorkflowStatus,
)
from adproof.generator.generator import GenerationTask, generate_ad
from adproof.infrastructure.safe_http import SafeHttpClient
from adproof.infrastructure.settings import Settings
from adproof.model_client import ModelClient, ModelClientError
from adproof.remediator.remediator import remediate_copy
from adproof.verifier.verifier import VerificationDependencies, verify_campaign


async def run_generation_workflow(
    text: str,
    *,
    index: Any,
    model: ModelClient,
    settings: Settings,
    policies: dict[str, Any],
    offline: bool = False,
    gateway: Any | None = None,
) -> AuditReport:
    audit_id = uuid.uuid4().hex
    campaign_id = f"generation-{audit_id[:12]}"
    candidate_id = f"candidate-{uuid.uuid4().hex[:12]}"
    deadline = datetime.now(UTC) + timedelta(seconds=settings.workflow_deadline_seconds)
    if gateway:
        generation_result = await gateway.generate(
            GenerationTask(
                audit_id=audit_id,
                request_id=uuid.uuid4().hex,
                campaign_id=campaign_id,
                candidate_id=candidate_id,
                prompt=text,
                deadline=deadline,
            )
        )
        if isinstance(generation_result, TypedError):
            raise ModelClientError(generation_result)
        generated = generation_result.model_dump(mode="json")
    else:
        generated = await generate_ad(text, index=index, model=model, deadline=deadline)
    request = generated["request"]
    ad = generated["generated_ad"]
    ad_copy = (
        "\n".join([*ad["headlines"], *ad["descriptions"]])
        if request["platform"] == "google_ads"
        else f"{ad['primary_text']}\n{ad['headline']}"
    )
    index.ensure_built()
    landing_page = index.document_for_url(ad["final_url"])
    if landing_page is None:
        raise ValueError("generated final URL does not match a corpus product page")
    context = CampaignContext(
        platform=request["platform"],
        jurisdiction=request["jurisdiction"],
        language=request["language"],
        audience=request["audience"],
        product_category="electronics",
    )
    candidate = CreativeCandidate(
        campaign_id=campaign_id,
        candidate_id=candidate_id,
        creative_version=1,
        phase=Phase.ORIGINAL,
        ad_copy=ad_copy,
        source_image_sha256="",
        model_input_sha256="",
        asset_ref=ad["final_url"],
        context=context,
    )
    verification = VerificationDependencies(
        http=SafeHttpClient(),
        model=model,
        policy=policies,
        corpus_index=index,
    )
    original_request = VerificationRequest(
        audit_id=audit_id,
        request_id=uuid.uuid4().hex,
        campaign_id=campaign_id,
        candidate_id=candidate_id,
        creative_version=1,
        phase=Phase.ORIGINAL,
        ad_copy=ad_copy,
        landing_page_url=ad["final_url"],
        context=context,
        image_inspection_status=InspectionStatus.NOT_APPLICABLE,
        corpus_mode=True,
        corpus_document_id=landing_page.doc_id,
        deadline=deadline,
    )
    original = (
        await gateway.verify(original_request)
        if gateway
        else await verify_campaign(original_request, verification)
    )
    if isinstance(original, TypedError):
        raise ModelClientError(original)
    repair_result = None
    revised_candidate = None
    revised = None
    selected_candidate_id = candidate_id
    final_decision = original.decision
    repair_verified = False
    errors = list(original.errors)
    if original.decision == Decision.FIX_REQUIRED and original.issues:
        repaired_id = f"candidate-{uuid.uuid4().hex[:12]}"
        repair_request = RepairRequest(
            audit_id=audit_id,
            request_id=uuid.uuid4().hex,
            campaign_id=campaign_id,
            original_candidate_id=candidate_id,
            candidate_id=repaired_id,
            ad_copy=ad_copy,
            issues=original.issues,
            claims=original.claims,
            evidence=original.evidence,
            deadline=deadline,
        )
        repair_result = (
            await gateway.repair(repair_request)
            if gateway
            else await remediate_copy(
                audit_id=audit_id,
                candidate_id=candidate_id,
                ad_copy=ad_copy,
                issues=original.issues,
                claims=original.claims,
                evidence=original.evidence,
                model=model,
                deadline=deadline,
            )
        )
        if isinstance(repair_result, TypedError):
            raise ModelClientError(repair_result)
        errors.extend(repair_result.errors)
        revised_candidate = candidate.model_copy(
            update={
                "candidate_id": repaired_id,
                "creative_version": 2,
                "phase": Phase.REPAIRED,
                "ad_copy": repair_result.repaired_copy,
            }
        )
        revised_request = original_request.model_copy(
            update={
                "candidate_id": repaired_id,
                "creative_version": 2,
                "phase": Phase.REPAIRED,
                "ad_copy": repair_result.repaired_copy,
                "request_id": uuid.uuid4().hex,
            }
        )
        revised = (
            await gateway.verify(revised_request)
            if gateway
            else await verify_campaign(revised_request, verification)
        )
        if isinstance(revised, TypedError):
            raise ModelClientError(revised)
        errors.extend(revised.errors)
        selected_candidate_id = repaired_id
        final_decision = revised.decision
        repair_verified = (
            revised.decision == Decision.PASS
            and repair_result.repaired_copy != ad_copy
            and not repair_result.errors
        )

    decision_basis = (
        "Generated text was independently checked against the company corpus."
        if final_decision == Decision.PASS
        else "The generated ad has unresolved issues or incomplete verification coverage."
    )
    return AuditReport(
        audit_id=audit_id,
        execution_mode=ExecutionMode.MOCK if offline else ExecutionMode.LIVE,
        workflow_status=(
            WorkflowStatus.COMPLETED
            if original.audit_complete and (revised is None or revised.audit_complete)
            else WorkflowStatus.PARTIAL
        ),
        scope="Corpus-grounded text ad preflight; no ad publishing or platform certification.",
        original_candidate=candidate,
        original_audit=original,
        repair_proposal=repair_result,
        revised_candidate=revised_candidate,
        revised_audit=revised,
        selected_candidate_id=selected_candidate_id,
        final_decision=final_decision,
        final_decision_basis=decision_basis,
        repair_verified=repair_verified,
        unresolved_issues=(revised.issues if revised else original.issues),
        coverage=(revised.coverage if revised else original.coverage),
        errors=errors,
        model_provider=settings.model_provider or "unknown",
        configured_model=settings.active_model,
        model_specs=settings.model_specs,
        model_versions={"ad_generation": generated["model_version"]},
        generation_request=request,
        generated_ad=ad,
    )
