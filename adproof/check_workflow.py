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
    InspectionResult,
    InspectionStatus,
    ObservationKind,
    Phase,
    VerificationRequest,
    WorkflowStatus,
)
from adproof.generator.generator import _document_for_request, parse_generation_request
from adproof.infrastructure.image import ImageFreezeError, freeze_image
from adproof.infrastructure.safe_http import SafeHttpClient
from adproof.infrastructure.settings import Settings
from adproof.inspector.inspector import ImageInspector
from adproof.model_client import ModelClient, ModelClientError
from adproof.verifier.policy import PolicyEngine
from adproof.verifier.verifier import VerificationDependencies
from adproof.workflow_cycle import verify_with_one_repair


class CheckWorkflowError(RuntimeError):
    pass


async def run_check_workflow(
    ad_text: str,
    *,
    index: Any,
    model: ModelClient,
    settings: Settings,
    policies: dict[str, PolicyEngine],
    image: bytes | None = None,
    image_inspector: Any | None = None,
    gateway: Any | None = None,
    offline: bool = False,
) -> AuditReport:
    audit_id = uuid.uuid4().hex
    campaign_id = f"check-{audit_id[:12]}"
    candidate_id = f"candidate-{uuid.uuid4().hex[:12]}"
    deadline = datetime.now(UTC) + timedelta(seconds=settings.workflow_deadline_seconds)
    inspection: InspectionResult | None = None
    frozen = None
    if image is not None:
        try:
            frozen = freeze_image(image)
        except ImageFreezeError as exc:
            raise CheckWorkflowError(str(exc)) from exc
        inspector = image_inspector or ImageInspector(model)
        inspection = await inspector.inspect(
            candidate_id=candidate_id,
            image_sha256=frozen.model_input_sha256,
            image_bytes=frozen.model_input,
            deadline=deadline,
        )
        if inspection.status == InspectionStatus.FAILED or inspection.errors:
            raise CheckWorkflowError("Image inspection failed; a human review is required.")

    detected_text = "\n".join(
        item.text
        for item in (inspection.observations if inspection else [])
        if item.kind == ObservationKind.VISIBLE_TEXT and item.text.strip()
    )
    effective_text = ad_text.strip() or detected_text
    if len(effective_text) > 4096:
        raise CheckWorkflowError("Ad text exceeds the 4096 character limit.")

    if not effective_text and image is None:
        raise CheckWorkflowError("Usage: check <ad text>.")
    if not effective_text:
        raise CheckWorkflowError("Couldn't match this ad to a product in the company data.")
    request = parse_generation_request(effective_text[:2048])
    index.ensure_built()
    chunks = index.retrieve(effective_text, top_k=6)
    landing_page = _document_for_request(index, chunks)
    if landing_page is None:
        raise CheckWorkflowError("Couldn't match this ad to a product in the company data.")
    policy = policies.get(request.platform)
    if policy is None:
        raise CheckWorkflowError("The requested platform is outside the supported scope.")
    context = CampaignContext(
        platform=request.platform,
        jurisdiction=request.jurisdiction,
        language=request.language,
        audience=request.audience,
        product_category="electronics",
    )
    ad_copy = effective_text
    candidate = CreativeCandidate(
        campaign_id=campaign_id,
        candidate_id=candidate_id,
        creative_version=1,
        phase=Phase.ORIGINAL,
        ad_copy=ad_copy,
        source_image_sha256=frozen.source_image_sha256 if frozen else "",
        model_input_sha256=frozen.model_input_sha256 if frozen else "",
        asset_ref="uploaded-image" if frozen else landing_page.url,
        context=context,
        transformation_metadata=frozen.transformation_metadata if frozen else {},
    )
    request_status = inspection.status if inspection else InspectionStatus.NOT_APPLICABLE
    verification_request = VerificationRequest(
        audit_id=audit_id,
        request_id=uuid.uuid4().hex,
        campaign_id=campaign_id,
        candidate_id=candidate_id,
        creative_version=1,
        phase=Phase.ORIGINAL,
        ad_copy=ad_copy,
        landing_page_url=landing_page.url,
        context=context,
        image_observations=inspection.observations if inspection else [],
        image_inspection_status=request_status,
        corpus_mode=True,
        corpus_document_id=landing_page.doc_id,
        deadline=deadline,
    )
    http = SafeHttpClient()
    verification = VerificationDependencies(
        http=http,
        model=model,
        policy=policy,
        corpus_index=index,
    )
    try:
        cycle = await verify_with_one_repair(
            candidate,
            verification_request,
            verification=verification,
            model=model,
            gateway=gateway,
            recheck_image_status=InspectionStatus.NOT_APPLICABLE,
            image_text_replacement=image is not None,
        )
    except ModelClientError:
        raise
    finally:
        await http.close()

    final_audit = cycle.revised or cycle.original
    final_decision = cycle.final_decision
    return AuditReport(
        audit_id=audit_id,
        execution_mode=ExecutionMode.MOCK if offline else ExecutionMode.LIVE,
        workflow_status=(
            WorkflowStatus.COMPLETED
            if cycle.original.audit_complete
            and (cycle.revised is None or cycle.revised.audit_complete)
            else WorkflowStatus.PARTIAL
        ),
        scope="Corpus-grounded text/image ad preflight; no ad publishing or platform certification.",
        original_candidate=candidate,
        original_audit=cycle.original,
        repair_proposal=cycle.repair,
        revised_candidate=cycle.revised_candidate,
        revised_audit=cycle.revised,
        selected_candidate_id=cycle.selected_candidate_id,
        final_decision=final_decision,
        final_decision_basis=(
            "The ad was independently checked against the company corpus."
            if final_decision == Decision.PASS
            else "The ad has unresolved issues or incomplete verification coverage."
        ),
        repair_verified=cycle.repair_verified,
        unresolved_issues=final_audit.issues,
        coverage=final_audit.coverage,
        errors=cycle.errors,
        model_provider=settings.model_provider or "unknown",
        configured_model=settings.active_model,
        model_specs=settings.model_specs,
        model_versions=({"image_inspection": inspection.model_version} if inspection else {}),
        check_input_type="image" if image is not None else "text",
        image_detected_text=detected_text if image is not None else None,
    )
