from __future__ import annotations

import asyncio
import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from adproof.domain.decision import select_report
from adproof.domain.models import (
    AuditReport,
    CampaignInput,
    CreativeCandidate,
    Decision,
    ExecutionMode,
    Phase,
    RepairRequest,
    RepairResult,
    TypedError,
    TypedErrorCode,
    VerificationRequest,
    VerificationResult,
    WorkflowStatus,
)
from adproof.infrastructure.budget import ModelCallBudget
from adproof.infrastructure.image import ImageFreezeError, freeze_image
from adproof.infrastructure.safe_http import SafeFetchError, SafeHttpClient
from adproof.infrastructure.settings import Settings
from adproof.infrastructure.store import SQLiteStore
from adproof.infrastructure.telemetry import record_event, stage_span
from adproof.inspector.inspector import ImageInspector
from adproof.orchestrator.gateway import LocalGateway

RESERVE_SECONDS = 5


@dataclass
class WorkflowDependencies:
    http: SafeHttpClient
    inspector: ImageInspector
    gateway: Any
    store: SQLiteStore
    budget: ModelCallBudget
    settings: Settings
    execution_mode: ExecutionMode = ExecutionMode.LIVE
    max_audits: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(2))
    audit_locks: dict[str, asyncio.Lock] = field(default_factory=dict)


def _as_error(exc: Exception, *, source: str | None = None) -> TypedError:
    if isinstance(exc, SafeFetchError):
        code = exc.code
    elif isinstance(exc, ImageFreezeError):
        code = exc.code
    else:
        code = TypedErrorCode.INTERNAL
    return TypedError(code=code, message=str(exc), source=source)


async def run_campaign(
    campaign: CampaignInput,
    *,
    owner: str,
    session_id: str,
    dependencies: WorkflowDependencies,
) -> AuditReport:
    audit_id = uuid.uuid4().hex
    payload_hash = hashlib.sha256(campaign.model_dump_json().encode()).hexdigest()
    existing = dependencies.store.claim_idempotency(
        scope=f"{owner}:{session_id}",
        request_id=campaign.request_id,
        payload_hash=payload_hash,
        audit_id=audit_id,
    )
    if isinstance(existing, TypedErrorCode):
        raise ValueError("request_id was already used with a different campaign payload")
    if existing != audit_id:
        stored = dependencies.store.get_workflow(existing, owner=owner, session_id=session_id)
        if stored and stored.get("payload", {}).get("report"):
            return AuditReport.model_validate(stored["payload"]["report"])
        raise RuntimeError("an identical campaign is already in progress")

    deadline = datetime.now(UTC) + timedelta(
        seconds=dependencies.settings.workflow_deadline_seconds
    )
    timestamps: dict[str, datetime] = {"received": datetime.now(UTC)}
    errors: list[TypedError] = []
    locks = dependencies.audit_locks.setdefault(campaign.campaign_id, asyncio.Lock())
    started = asyncio.get_running_loop().time()
    record_event(
        "audit_started",
        audit_id=audit_id,
        role="orchestrator",
        execution_mode=dependencies.execution_mode.value,
    )
    async with dependencies.max_audits, locks:
        dependencies.store.save_workflow(
            audit_id=audit_id,
            owner=owner,
            session_id=session_id,
            state="VALIDATING",
            payload={"request_id": campaign.request_id, "payload_hash": payload_hash},
        )
        if any(
            value is None
            for value in (
                campaign.context.platform,
                campaign.context.jurisdiction,
                campaign.context.language,
                campaign.context.audience,
                campaign.context.product_category,
            )
        ):
            errors.append(
                TypedError(
                    code=TypedErrorCode.UNSUPPORTED_CONTEXT,
                    message="Platform, jurisdiction, language, audience, and product category are required.",
                )
            )
        candidate_id = f"candidate-{uuid.uuid4().hex[:12]}"
        try:
            with stage_span("image_fetch_and_freeze", audit_id=audit_id, role="orchestrator"):
                fetched = await dependencies.http.fetch(
                    campaign.creative.image_url, max_bytes=8 * 1024 * 1024
                )
                frozen = freeze_image(fetched.content)
        except Exception as exc:
            errors.append(_as_error(exc, source=campaign.creative.image_url))
            frozen = None
        if frozen is None:
            original_candidate = CreativeCandidate(
                campaign_id=campaign.campaign_id,
                candidate_id=candidate_id,
                creative_version=campaign.creative_version,
                phase=Phase.ORIGINAL,
                ad_copy=campaign.creative.ad_copy,
                source_image_sha256="",
                model_input_sha256="",
                asset_ref=campaign.creative.image_url,
                context=campaign.context,
            )
            report = AuditReport(
                audit_id=audit_id,
                execution_mode=dependencies.execution_mode,
                workflow_status=WorkflowStatus.PARTIAL,
                scope="Google Ads, US, English, adult-targeted general consumer electronics; preflight only.",
                original_candidate=original_candidate,
                selected_candidate_id=candidate_id,
                final_decision=Decision.HUMAN_REVIEW,
                final_decision_basis="The creative image could not be safely retrieved and frozen.",
                repair_verified=False,
                model_provider=dependencies.settings.model_provider,
                configured_model=dependencies.settings.active_model,
                errors=errors,
                timestamps=timestamps,
            )
            dependencies.store.save_workflow(
                audit_id=audit_id,
                owner=owner,
                session_id=session_id,
                state="PARTIAL",
                payload={
                    "request_id": campaign.request_id,
                    "report": report.model_dump(mode="json"),
                },
            )
            return report

        original_candidate = CreativeCandidate(
            campaign_id=campaign.campaign_id,
            candidate_id=candidate_id,
            creative_version=campaign.creative_version,
            phase=Phase.ORIGINAL,
            ad_copy=campaign.creative.ad_copy,
            source_image_sha256=frozen.source_image_sha256,
            model_input_sha256=frozen.model_input_sha256,
            asset_ref=campaign.creative.image_url,
            context=campaign.context,
            transformation_metadata=frozen.transformation_metadata,
        )
        timestamps["validating"] = datetime.now(UTC)
        dependencies.store.save_workflow(
            audit_id=audit_id,
            owner=owner,
            session_id=session_id,
            state="INSPECTING",
            payload={"request_id": campaign.request_id, "candidate_id": candidate_id},
        )
        with stage_span("inspect", audit_id=audit_id, role="orchestrator"):
            inspection = await dependencies.inspector.inspect(
                candidate_id=candidate_id,
                image_sha256=frozen.model_input_sha256,
                image_bytes=frozen.model_input,
                deadline=deadline - timedelta(seconds=RESERVE_SECONDS),
            )
        timestamps["inspecting"] = datetime.now(UTC)
        verify_request = VerificationRequest(
            audit_id=audit_id,
            request_id=campaign.request_id,
            campaign_id=campaign.campaign_id,
            candidate_id=candidate_id,
            creative_version=campaign.creative_version,
            phase=Phase.ORIGINAL,
            ad_copy=campaign.creative.ad_copy,
            landing_page_url=campaign.landing_page_url,
            evidence_documents=campaign.evidence_documents,
            context=campaign.context,
            product_context=campaign.product_context,
            image_observations=inspection.observations,
            image_inspection_status=inspection.status,
            deadline=deadline - timedelta(seconds=RESERVE_SECONDS),
        )
        original_audit: VerificationResult | None = None
        repair_proposal: RepairResult | None = None
        revised_candidate: CreativeCandidate | None = None
        revised_audit: VerificationResult | None = None
        nonretryable_model_failure = any(
            error.code in {TypedErrorCode.MODEL_AUTH, TypedErrorCode.MODEL_UNAVAILABLE}
            and not error.retryable
            for error in inspection.errors
        )
        if not nonretryable_model_failure and datetime.now(UTC) < deadline - timedelta(
            seconds=RESERVE_SECONDS
        ):
            dependencies.store.save_workflow(
                audit_id=audit_id,
                owner=owner,
                session_id=session_id,
                state="VERIFYING",
                payload={"request_id": campaign.request_id, "candidate_id": candidate_id},
            )
            with stage_span("verify_original", audit_id=audit_id, role="orchestrator"):
                verify_result = await dependencies.gateway.verify(verify_request)
            if isinstance(verify_result, VerificationResult):
                original_audit = verify_result
            else:
                errors.append(verify_result)
        elif not nonretryable_model_failure:
            errors.append(
                TypedError(
                    code=TypedErrorCode.TIMEOUT,
                    message="Workflow deadline expired before verification.",
                )
            )
        timestamps["original_ready"] = datetime.now(UTC)

        if (
            original_audit is not None
            and campaign.repair_mode == "repair_once"
            and original_audit.decision.value == "FIX_REQUIRED"
            and datetime.now(UTC) < deadline - timedelta(seconds=RESERVE_SECONDS)
        ):
            dependencies.store.save_workflow(
                audit_id=audit_id,
                owner=owner,
                session_id=session_id,
                state="REPAIRING",
                payload={"request_id": campaign.request_id, "candidate_id": candidate_id},
            )
            repair_request = RepairRequest(
                audit_id=audit_id,
                request_id=campaign.request_id,
                campaign_id=campaign.campaign_id,
                original_candidate_id=candidate_id,
                candidate_id=candidate_id,
                ad_copy=campaign.creative.ad_copy,
                claims=original_audit.claims,
                evidence=original_audit.evidence,
                issues=original_audit.issues,
                deadline=deadline - timedelta(seconds=RESERVE_SECONDS),
            )
            with stage_span("repair", audit_id=audit_id, role="orchestrator"):
                repair_result = await dependencies.gateway.repair(repair_request)
            if isinstance(repair_result, RepairResult):
                repair_proposal = repair_result
                revised_candidate = CreativeCandidate(
                    campaign_id=campaign.campaign_id,
                    candidate_id=repair_result.candidate_id,
                    creative_version=campaign.creative_version + 1,
                    phase=Phase.REPAIRED,
                    ad_copy=repair_result.repaired_copy,
                    source_image_sha256=original_candidate.source_image_sha256,
                    model_input_sha256=original_candidate.model_input_sha256,
                    asset_ref=original_candidate.asset_ref,
                    context=original_candidate.context,
                    transformation_metadata={
                        **original_candidate.transformation_metadata,
                        "image_unchanged": True,
                    },
                )
                if repair_result.repaired_copy != campaign.creative.ad_copy:
                    dependencies.store.save_workflow(
                        audit_id=audit_id,
                        owner=owner,
                        session_id=session_id,
                        state="REVERIFYING",
                        payload={
                            "request_id": campaign.request_id,
                            "candidate_id": revised_candidate.candidate_id,
                        },
                    )
                    revised_request = verify_request.model_copy(
                        update={
                            "candidate_id": revised_candidate.candidate_id,
                            "creative_version": revised_candidate.creative_version,
                            "phase": Phase.REPAIRED,
                            "ad_copy": revised_candidate.ad_copy,
                        }
                    )
                    with stage_span("reverify", audit_id=audit_id, role="orchestrator"):
                        revised_result = await dependencies.gateway.verify(revised_request)
                    if isinstance(revised_result, VerificationResult):
                        revised_audit = revised_result
                    else:
                        errors.append(revised_result)
            else:
                errors.append(repair_result)

        if original_audit is None:
            selection = select_report(
                original=None,
                original_candidate_id=candidate_id,
                repair_candidate_id=revised_candidate.candidate_id if revised_candidate else None,
                repair_errors=errors,
            )
        else:
            selection = select_report(
                original=original_audit,
                repair_candidate_id=revised_candidate.candidate_id if revised_candidate else None,
                revised=revised_audit,
                repair_errors=errors,
            )
        errors.extend(inspection.errors)
        model_versions = {"inspector": inspection.model_version}
        if original_audit:
            model_versions["verifier_original"] = original_audit.metrics.get(
                "model_version", "configured"
            )
        if revised_audit:
            model_versions["verifier_revised"] = revised_audit.metrics.get(
                "model_version", "configured"
            )
        report = AuditReport(
            audit_id=audit_id,
            execution_mode=dependencies.execution_mode,
            workflow_status=selection.workflow_status,
            scope="Google Ads, US, English, adult-targeted general consumer electronics; preflight only.",
            original_candidate=original_candidate,
            original_audit=original_audit,
            repair_proposal=repair_proposal,
            revised_candidate=revised_candidate,
            revised_audit=revised_audit,
            selected_candidate_id=selection.selected_candidate_id,
            final_decision=selection.final_decision,
            final_decision_basis=selection.final_decision_basis,
            repair_verified=selection.repair_verified,
            unresolved_issues=selection.unresolved_issues,
            coverage=selection.coverage,
            errors=[*selection.errors, *inspection.errors],
            source_versions={
                "policy_catalog": original_audit.policy_catalog_version
                if original_audit
                else "unknown"
            },
            model_provider=dependencies.settings.model_provider,
            configured_model=dependencies.settings.active_model,
            model_versions=model_versions,
            timestamps={**timestamps, "completed": datetime.now(UTC)},
            timings={"total_seconds": asyncio.get_running_loop().time() - started},
        )
        state = report.workflow_status.value
        dependencies.store.save_workflow(
            audit_id=audit_id,
            owner=owner,
            session_id=session_id,
            state=state,
            payload={
                "request_id": campaign.request_id,
                "campaign": campaign.model_dump(mode="json"),
                "report": report.model_dump(mode="json"),
            },
        )
        record_event(
            "audit_completed",
            audit_id=audit_id,
            role="orchestrator",
            duration=report.timings["total_seconds"],
            result=report.final_decision.value,
            execution_mode=dependencies.execution_mode.value,
        )
        return report


def build_live_dependencies(settings: Settings) -> WorkflowDependencies:
    import json

    from adproof.infrastructure.telemetry import initialize_telemetry
    from adproof.model_client import build_model_client
    from adproof.verifier.policy import PolicyEngine
    from adproof.verifier.verifier import VerificationDependencies

    initialize_telemetry(settings, role="orchestrator")
    budget = ModelCallBudget(20)
    model = build_model_client(settings, budget)
    http = SafeHttpClient()
    root = Path(__file__).resolve().parents[2]
    policy = PolicyEngine(
        json.loads((root / "data/policies/catalog.json").read_text(encoding="utf-8")),
        json.loads(
            (root / "data/policies/packs/google_ads_us_electronics_v1.json").read_text(
                encoding="utf-8"
            )
        ),
    )
    verification_dependencies = VerificationDependencies(http=http, model=model, policy=policy)
    return WorkflowDependencies(
        http=http,
        inspector=ImageInspector(model),
        gateway=LocalGateway(verification_dependencies, model),
        store=SQLiteStore(settings.runtime_dir / "adproof.sqlite3"),
        budget=budget,
        settings=settings,
    )
