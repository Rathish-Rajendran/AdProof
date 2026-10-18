import base64
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from adproof.check_workflow import CheckWorkflowError, run_check_workflow
from adproof.domain.models import (
    CampaignContext,
    ClaimSource,
    ClaimStatus,
    ClaimType,
    CoverageStatus,
    Decision,
    InspectionResult,
    InspectionStatus,
    Observation,
    ObservationKind,
    Phase,
    VerificationRequest,
)
from adproof.generate import _offline_model
from adproof.generator.generator import GenerationResult
from adproof.generator.workflow import run_generation_workflow
from adproof.infrastructure.settings import Settings
from adproof.model_client import FakeModelClient
from adproof.orchestrator.report_view import (
    _compliance_summary,
    _score_checks,
    render_generation_failure,
    render_report,
    report_summary,
)
from adproof.rag.chunker import CorpusChunk, CorpusDocument
from adproof.rag.index import CorpusIndex
from adproof.remediator.remediator import _RepairOutput
from adproof.transport.models import SpecialistOperation, SpecialistResult, validate_result_shape
from adproof.verifier.policy import PolicyEngine
from adproof.verifier.verifier import (
    VerificationDependencies,
    _Assessment,
    _AssessmentOutput,
    _claim_extraction_prompt,
    _ClaimExtraction,
    _ExtractedClaim,
    verify_campaign,
)

ROOT = Path(__file__).resolve().parents[1]
PAGE_URL = "https://aerobeat.example/products/ab-01"
PAGE_TEXT = (
    "The AeroBeat AB-01 is a synthetic product. It is not waterproof and should not be submerged. "
    "It is splash-resistant for everyday use."
)


class FakeCorpusIndex:
    def __init__(self, page_text=PAGE_TEXT):
        self.document = CorpusDocument(
            "aerobeat-ab01-product",
            "AeroBeat AB-01",
            PAGE_URL,
            "product_page",
            page_text,
            "document-sha",
        )
        self.chunk = CorpusChunk(
            "aerobeat-ab01-product#1",
            self.document.doc_id,
            self.document.title,
            "Product facts",
            PAGE_URL,
            page_text,
            "chunk-sha",
        )

    def ensure_built(self):
        return None

    def retrieve(self, _query, *, top_k=6):
        return [self.chunk][:top_k]

    def documents(self):
        return [self.document]

    def get_document(self, doc_id):
        return self.document if doc_id == self.document.doc_id else None

    def document_for_url(self, url):
        return self.document if url == PAGE_URL else None


class FakeCorpusEmbedder:
    def embed(self, texts):
        return ([float(len(text)), float(text.casefold().count("battery"))] for text in texts)


def _policy() -> PolicyEngine:
    return PolicyEngine.from_files(
        ROOT / "data/policies/catalog.json",
        ROOT / "data/policies/packs/google_ads_us_electronics_v1.json",
    )


def _request(
    copy: str,
    audience: str = "adults",
    *,
    context_overrides: dict | None = None,
) -> VerificationRequest:
    context = CampaignContext(
        platform="google_ads",
        jurisdiction="US",
        language="en",
        audience=audience,
        product_category="electronics",
    )
    if context_overrides:
        context = context.model_copy(update=context_overrides)
    return VerificationRequest(
        audit_id="audit-corpus",
        request_id="request-corpus",
        campaign_id="campaign-corpus",
        candidate_id="candidate-corpus",
        creative_version=1,
        phase=Phase.ORIGINAL,
        ad_copy=copy,
        landing_page_url=PAGE_URL,
        context=context,
        image_inspection_status=InspectionStatus.NOT_APPLICABLE,
        corpus_mode=True,
        corpus_document_id="aerobeat-ab01-product",
        deadline=datetime.now(UTC) + timedelta(minutes=2),
    )


async def _verify_claim(
    copy: str,
    *,
    claim_text: str,
    status: ClaimStatus,
    quote: str,
    audience="adults",
    source_index: int = 1,
    context_overrides: dict | None = None,
):
    model = FakeModelClient(
        [
            _ClaimExtraction(
                claims=[
                    _ExtractedClaim(
                        claim=claim_text,
                        source=ClaimSource.AD_TEXT,
                        claim_type=ClaimType.OTHER_OBJECTIVE,
                    )
                ]
            ),
            _AssessmentOutput(
                assessments=[
                    _Assessment(
                        claim_id="claim-1",
                        status=status,
                        source_index=source_index,
                        quote=quote,
                        explanation="Corpus assessment.",
                    )
                ]
            ),
        ]
    )
    index = FakeCorpusIndex()
    return await verify_campaign(
        _request(copy, audience, context_overrides=context_overrides),
        VerificationDependencies(
            http=None,  # type: ignore[arg-type]
            model=model,
            policy=_policy(),
            corpus_index=index,
        ),
    )


@pytest.mark.asyncio
async def test_corpus_verification_validates_quotes_and_not_applicable_image():
    result = await _verify_claim(
        "Splash-resistant AeroBeat headphones.",
        claim_text="splash-resistant",
        status=ClaimStatus.SUPPORTED,
        quote="splash-resistant for everyday use",
    )
    assert result.decision == Decision.PASS
    assert result.coverage.image.status.value == "NOT_APPLICABLE"
    evidence = next(item for item in result.evidence if item.locator.endswith("#1"))
    assert evidence.source_type == "company_corpus"
    assert evidence.document_id == "aerobeat-ab01-product"
    assert "splash-resistant for everyday use" in evidence.excerpt


@pytest.mark.asyncio
async def test_corpus_verification_contradicts_waterproof_and_minors_require_review():
    result = await _verify_claim(
        "AeroBeat is waterproof.",
        claim_text="waterproof",
        status=ClaimStatus.CONTRADICTED,
        quote="not waterproof",
    )
    assert result.decision == Decision.FIX_REQUIRED
    quote_evidence = next(item for item in result.evidence if item.excerpt == "not waterproof")
    assert quote_evidence.locator.endswith("#1")

    minors = await _verify_claim(
        "Splash-resistant AeroBeat headphones.",
        claim_text="splash-resistant",
        status=ClaimStatus.SUPPORTED,
        quote="splash-resistant for everyday use",
        audience="minors",
    )
    assert minors.decision == Decision.HUMAN_REVIEW
    assert any(
        error.message
        == "This ad targets minors, which is outside the supported adult-audience scope; "
        "a human review is required."
        for error in minors.errors
    )


@pytest.mark.asyncio
async def test_nonmatching_audience_platform_and_jurisdiction_have_specific_errors():
    unsupported_audience = await _verify_claim(
        "Splash-resistant AeroBeat headphones.",
        claim_text="splash-resistant",
        status=ClaimStatus.SUPPORTED,
        quote="splash-resistant for everyday use",
        audience="other",
    )
    assert any(
        error.message
        == "The requested audience is outside the supported scope; a human review is required."
        for error in unsupported_audience.errors
    )

    unsupported_platform = await _verify_claim(
        "Splash-resistant AeroBeat headphones.",
        claim_text="splash-resistant",
        status=ClaimStatus.SUPPORTED,
        quote="splash-resistant for everyday use",
        context_overrides={"platform": "microsoft_ads"},
    )
    assert any(
        error.message
        == "The requested platform microsoft_ads is outside the supported google_ads scope; "
        "a human review is required."
        for error in unsupported_platform.errors
    )

    unsupported_jurisdiction = await _verify_claim(
        "Splash-resistant AeroBeat headphones.",
        claim_text="splash-resistant",
        status=ClaimStatus.SUPPORTED,
        quote="splash-resistant for everyday use",
        context_overrides={"jurisdiction": "CA"},
    )
    assert any(
        error.message == "The requested jurisdiction CA is outside the supported US scope; "
        "a human review is required."
        for error in unsupported_jurisdiction.errors
    )


@pytest.mark.asyncio
async def test_corpus_verification_accepts_quote_from_product_page_only():
    result = await _verify_claim(
        "AeroBeat is waterproof.",
        claim_text="waterproof",
        status=ClaimStatus.CONTRADICTED,
        quote="not waterproof",
        source_index=0,
    )

    assert result.decision == Decision.FIX_REQUIRED
    assert not any(error.code.value == "INVALID_EVIDENCE" for error in result.errors)


@pytest.mark.asyncio
async def test_eight_claim_corpus_audit_fits_transport_and_has_only_referenced_evidence(
    tmp_path,
):
    index = CorpusIndex(
        path=tmp_path / "corpus_index.sqlite3",
        corpus_path=ROOT / "data/corpus/aerobeat",
        embedder=FakeCorpusEmbedder(),
    )
    index.build()
    claim_quotes = [
        ("AB-01 is a wireless over-ear headphone.", "wireless over-ear headphone"),
        ("AB-01 is for everyday listening.", "everyday listening"),
        ("AB-01 is splash-resistant for everyday use.", "splash-resistant for everyday use"),
        ("AB-01 has an IPX4 rating.", "has an IPX4 rating"),
        ("AB-01 is not waterproof.", "not waterproof"),
        ("AB-01 should not be submerged.", "should not be submerged"),
        ("AB-01 uses Bluetooth 5.3.", "uses Bluetooth 5.3"),
        ("AB-01 uses USB-C charging.", "USB-C charging"),
    ]
    model = FakeModelClient(
        [
            _ClaimExtraction(
                claims=[
                    _ExtractedClaim(
                        claim=claim,
                        source=ClaimSource.AD_TEXT,
                        claim_type=ClaimType.OTHER_OBJECTIVE,
                    )
                    for claim, _ in claim_quotes
                ]
            ),
            _AssessmentOutput(
                assessments=[
                    _Assessment(
                        claim_id=f"claim-{index}",
                        status=ClaimStatus.SUPPORTED,
                        source_index=0,
                        quote=quote,
                        explanation="The product page supports this claim.",
                    )
                    for index, (_, quote) in enumerate(claim_quotes, start=1)
                ]
            ),
        ]
    )

    result = await verify_campaign(
        _request(" ".join(claim for claim, _ in claim_quotes)),
        VerificationDependencies(
            http=None,  # type: ignore[arg-type]
            model=model,
            policy=_policy(),
            corpus_index=index,
        ),
    )

    evidence_by_id = {item.id: item for item in result.evidence}
    cited_evidence_ids = {
        evidence_id for claim in result.claims for evidence_id in claim.evidence_ids
    }
    product_page = next(item for item in result.evidence if item.locator.endswith("#page"))
    assert len(result.claims) == 8
    assert all(claim.status == ClaimStatus.SUPPORTED for claim in result.claims)
    assert all(
        evidence_id in evidence_by_id
        for claim in result.claims
        for evidence_id in claim.evidence_ids
    )
    assert {item.id for item in result.evidence} == cited_evidence_ids | {product_page.id}
    assert all(item.locator.endswith("#page") for item in result.evidence)
    assert len(product_page.excerpt) <= 500

    validate_result_shape(
        SpecialistResult(
            schema_version="1.0",
            audit_id=result.audit_id,
            task_id="task-corpus-8-claims",
            request_id="request-corpus",
            campaign_id=result.campaign_id,
            candidate_id=result.candidate_id,
            creative_version=result.creative_version,
            phase=result.phase.value,
            operation=SpecialistOperation.VERIFY,
            attempt=1,
            execution_mode="TEST",
            payload_json=result.model_dump_json(),
        )
    )


@pytest.mark.asyncio
async def test_offline_generation_workflow_repairs_and_rechecks():
    index = FakeCorpusIndex()
    prompt = "Generate a Google Ads ad for AeroBeat AB-01 headphones for US adults"
    settings = Settings()
    policies = {"google_ads": _policy(), "meta_ads": _policy()}
    report = await run_generation_workflow(
        prompt,
        index=index,
        model=_offline_model(index, prompt),  # type: ignore[arg-type]
        settings=settings,
        policies=policies,
        offline=True,
    )
    assert report.original_audit is not None
    assert report.generation_request is not None
    assert report.generated_ad is not None
    assert report.repair_proposal is not None
    assert report.revised_candidate is not None
    assert report.revised_audit is not None
    assert list(report_summary(report)) == [
        "audit_id",
        "needs_review",
        "confidence",
        "summary",
        "ad",
        "compliance",
        "claims",
    ]
    generation_result = GenerationResult(
        request=report.generation_request,
        generated_ad=report.generated_ad,
        model_version=report.model_versions["ad_generation"],
        sources=[
            {"chunk_id": chunk.chunk_id, "title": chunk.title, "url": chunk.url}
            for chunk in index.retrieve(prompt, top_k=6)
        ],
    )

    def validate_specialist_payload(payload, *, operation, candidate_id, version, phase):
        validate_result_shape(
            SpecialistResult(
                schema_version="1.0",
                audit_id=report.audit_id,
                task_id=f"offline-{operation.value}-{phase.lower()}",
                request_id="offline-request",
                campaign_id=report.original_candidate.campaign_id,
                candidate_id=candidate_id,
                creative_version=version,
                phase=phase,
                operation=operation,
                attempt=1,
                execution_mode="MOCK",
                payload_json=payload.model_dump_json(),
            )
        )

    validate_specialist_payload(
        generation_result,
        operation=SpecialistOperation.GENERATE,
        candidate_id=report.original_candidate.candidate_id,
        version=1,
        phase="ORIGINAL",
    )
    validate_specialist_payload(
        report.original_audit,
        operation=SpecialistOperation.VERIFY,
        candidate_id=report.original_candidate.candidate_id,
        version=1,
        phase="ORIGINAL",
    )
    validate_specialist_payload(
        report.repair_proposal,
        operation=SpecialistOperation.REPAIR,
        candidate_id=report.revised_candidate.candidate_id,
        version=1,
        phase="REPAIR",
    )
    validate_specialist_payload(
        report.revised_audit,
        operation=SpecialistOperation.VERIFY,
        candidate_id=report.revised_candidate.candidate_id,
        version=2,
        phase="REPAIRED",
    )
    summary = report_summary(report)
    assert report.original_audit.decision == Decision.FIX_REQUIRED
    assert report.revised_audit.decision == Decision.PASS
    assert report.repair_verified is True
    assert summary["needs_review"] is False
    assert summary["compliance"] == "OK"
    assert summary["ad"] == {
        "platform": "google_ads",
        "ad_copy": report.repair_proposal.repaired_copy,
        "final_url": PAGE_URL,
    }
    assert summary["summary"].startswith(
        f"The first draft had {len(report.original_audit.issues)} issues; "
        "it was fixed once and re-checked. Ready to run: "
    )
    assert list(summary) == [
        "audit_id",
        "needs_review",
        "confidence",
        "summary",
        "ad",
        "compliance",
        "claims",
    ]
    assert summary["claims"]
    assert all("#" not in claim["source"] for claim in summary["claims"])


def _check_model(
    *,
    initial_claims,
    initial_assessments,
    repaired_copy: str | None = None,
    final_claims=None,
    final_assessments=None,
) -> FakeModelClient:
    responses = [
        _ClaimExtraction(claims=initial_claims),
        _AssessmentOutput(assessments=initial_assessments),
    ]
    if repaired_copy is not None:
        responses.extend(
            [
                _RepairOutput(
                    repaired_copy=repaired_copy,
                    changes=[],
                    unresolved_issue_ids=[],
                ),
                _ClaimExtraction(claims=final_claims or []),
                _AssessmentOutput(assessments=final_assessments or []),
            ]
        )
    return FakeModelClient(responses, model_version="fake-check-model")


def _text_claim(text: str, *, source=ClaimSource.AD_TEXT, observation_id=None):
    return _ExtractedClaim(
        claim=text,
        source=source,
        claim_type=ClaimType.OTHER_OBJECTIVE,
        observation_id=observation_id,
    )


def _assessment(status: ClaimStatus, quote: str) -> _Assessment:
    return _Assessment(
        claim_id="claim-1",
        status=status,
        source_index=1,
        quote=quote,
        explanation="The product page directly supports or contradicts this claim.",
    )


class CapturingFakeModelClient(FakeModelClient):
    def __init__(self, responses):
        super().__init__(responses, model_version="capturing-fake")
        self.prompts = []

    async def generate_json(self, prompt_parts, schema, *, deadline, purpose):
        self.prompts.append((purpose, list(prompt_parts)))
        return await super().generate_json(
            prompt_parts,
            schema,
            deadline=deadline,
            purpose=purpose,
        )


def _validate_check_payloads(report):
    payloads = [
        (
            report.original_audit,
            SpecialistOperation.VERIFY,
            "ORIGINAL",
            report.original_candidate.candidate_id,
        ),
    ]
    if report.repair_proposal:
        payloads.append(
            (
                report.repair_proposal,
                SpecialistOperation.REPAIR,
                "REPAIR",
                report.revised_candidate.candidate_id,
            )
        )
    if report.revised_audit:
        payloads.append(
            (
                report.revised_audit,
                SpecialistOperation.VERIFY,
                "REPAIRED",
                report.revised_candidate.candidate_id,
            )
        )
    for index, (payload, operation, phase, candidate_id) in enumerate(payloads):
        validate_result_shape(
            SpecialistResult(
                schema_version="1.0",
                audit_id=report.audit_id,
                task_id=f"check-{operation.value}-{index}",
                request_id=f"check-request-{index}",
                campaign_id=report.original_candidate.campaign_id,
                candidate_id=candidate_id,
                creative_version=1 if phase == "ORIGINAL" else 2,
                phase=phase,
                operation=operation,
                attempt=1,
                execution_mode="MOCK",
                payload_json=payload.model_dump_json(),
            )
        )


def _parse_rendered_report(rendered: str):
    return json.loads(rendered.removeprefix("```json\n").removesuffix("\n```"))


@pytest.mark.asyncio
async def test_text_check_repairs_once_rechecks_and_returns_compact_shape():
    index = FakeCorpusIndex()
    model = _check_model(
        initial_claims=[_text_claim("completely waterproof")],
        initial_assessments=[_assessment(ClaimStatus.CONTRADICTED, "not waterproof")],
        repaired_copy="AeroBeat AB-01 is splash-resistant for everyday use.",
        final_claims=[_text_claim("splash-resistant for everyday use")],
        final_assessments=[_assessment(ClaimStatus.SUPPORTED, "splash-resistant for everyday use")],
    )
    report = await run_check_workflow(
        "AeroBeat AB-01 headphones are completely waterproof; take 50% off.",
        index=index,
        model=model,
        settings=Settings(),
        policies={"google_ads": _policy(), "meta_ads": _policy()},
        offline=True,
    )

    rendered = report_summary(report)
    assert report.repair_verified
    assert report.final_decision == Decision.PASS
    assert rendered["needs_review"] is False
    assert rendered["summary"].startswith(
        "The first draft had 1 issues; it was fixed once and re-checked."
    )
    assert rendered["compliance"] == "OK"
    assert rendered["ad"] == {
        "type": "text",
        "ad_copy": "AeroBeat AB-01 is splash-resistant for everyday use.",
    }
    assert list(rendered) == [
        "audit_id",
        "needs_review",
        "confidence",
        "summary",
        "ad",
        "compliance",
        "claims",
    ]
    _validate_check_payloads(report)


@pytest.mark.asyncio
async def test_supported_text_check_needs_no_repair_and_unknown_product_is_review():
    index = FakeCorpusIndex()
    report = await run_check_workflow(
        "AeroBeat AB-01 is splash-resistant for everyday use.",
        index=index,
        model=_check_model(
            initial_claims=[_text_claim("splash-resistant for everyday use")],
            initial_assessments=[
                _assessment(ClaimStatus.SUPPORTED, "splash-resistant for everyday use")
            ],
        ),
        settings=Settings(),
        policies={"google_ads": _policy(), "meta_ads": _policy()},
        offline=True,
    )
    rendered = report_summary(report)
    assert rendered["needs_review"] is False
    assert rendered["summary"].startswith("Ready to run:")
    assert rendered["compliance"] == "OK"
    assert report.repair_proposal is None
    _validate_check_payloads(report)

    class NoProductIndex(FakeCorpusIndex):
        def retrieve(self, _query, *, top_k=6):
            return []

    with pytest.raises(CheckWorkflowError, match="Couldn't match this ad"):
        await run_check_workflow(
            "A completely unknown product claim.",
            index=NoProductIndex(),
            model=FakeModelClient([]),
            settings=Settings(),
            policies={"google_ads": _policy(), "meta_ads": _policy()},
            offline=True,
        )
    failure = _parse_rendered_report(
        render_generation_failure(
            "A completely unknown product claim.",
            "Couldn't match this ad to a product in the company data.",
        )
    )
    assert failure["needs_review"] is True
    assert "Couldn't match this ad" in failure["summary"]


class FakeImageInspector:
    def __init__(self, text: str):
        self.text = text
        self.calls = 0

    async def inspect(self, *, candidate_id, image_sha256, image_bytes, deadline):
        self.calls += 1
        return InspectionResult(
            candidate_id=candidate_id,
            image_sha256=image_sha256,
            model_version="fake-inspector",
            prompt_version="test",
            status=InspectionStatus.COMPLETE,
            observations=[
                Observation(
                    observation_id="obs-1",
                    kind=ObservationKind.VISIBLE_TEXT,
                    text=self.text,
                )
            ],
        )


@pytest.mark.asyncio
async def test_uploaded_image_download_inspect_and_audit_returns_image_shape(monkeypatch):
    from uagents_core.contrib.protocols.chat import Resource, ResourceContent
    from uagents_core.identity import Identity

    from agents.orchestrator import main as orchestrator

    image = (ROOT / "data/fixtures/public/aerobeat-only49.png").read_bytes()
    download_calls = []

    class FakeStorage:
        def __init__(self, *, identity, storage_url):
            assert storage_url == "https://agentverse.ai/v1/storage"

        def download(self, asset_id):
            download_calls.append(asset_id)
            return {
                "contents": base64.b64encode(image).decode("ascii"),
                "mime_type": "image/png",
            }

    monkeypatch.setattr(orchestrator, "ExternalStorage", FakeStorage)
    content = ResourceContent(
        resource_id=uuid.uuid4(),
        resource=Resource(uri="agentverse://uploaded-image", metadata={}),
    )
    http = orchestrator.SafeHttpClient()
    try:
        downloaded = await orchestrator._download_resource_image(
            content,
            identity=Identity.from_seed("test-image-upload", 0),
            http=http,
        )
    finally:
        await http.close()
    assert downloaded == image
    assert download_calls == [str(content.resource_id)]

    inspector = FakeImageInspector("AeroBeat AB-01 is splash-resistant for everyday use.")
    report = await run_check_workflow(
        "",
        index=FakeCorpusIndex(),
        model=_check_model(
            initial_claims=[_text_claim("splash-resistant for everyday use")],
            initial_assessments=[
                _assessment(ClaimStatus.SUPPORTED, "splash-resistant for everyday use")
            ],
        ),
        settings=Settings(),
        policies={"google_ads": _policy(), "meta_ads": _policy()},
        image=downloaded,
        image_inspector=inspector,
        offline=True,
    )
    parsed = _parse_rendered_report(render_report(report))
    assert inspector.calls == 1
    assert parsed["needs_review"] is False
    assert parsed["compliance"] == "OK"
    assert parsed["summary"].startswith("Ready to run:")
    assert parsed["ad"] == {
        "type": "image",
        "detected_text": "AeroBeat AB-01 is splash-resistant for everyday use.",
        "fixed_text": None,
    }
    assert list(parsed) == [
        "audit_id",
        "needs_review",
        "confidence",
        "summary",
        "ad",
        "compliance",
        "claims",
    ]
    _validate_check_payloads(report)


@pytest.mark.asyncio
async def test_image_check_can_fix_text_and_invalid_images_return_safe_json():
    image = (ROOT / "data/fixtures/public/aerobeat-only49.png").read_bytes()
    inspector = FakeImageInspector("AeroBeat AB-01 is completely waterproof.")
    report = await run_check_workflow(
        "",
        index=FakeCorpusIndex(),
        model=_check_model(
            initial_claims=[_text_claim("completely waterproof")],
            initial_assessments=[_assessment(ClaimStatus.CONTRADICTED, "not waterproof")],
            repaired_copy="AeroBeat AB-01 is splash-resistant for everyday use.",
            final_claims=[_text_claim("splash-resistant for everyday use")],
            final_assessments=[
                _assessment(ClaimStatus.SUPPORTED, "splash-resistant for everyday use")
            ],
        ),
        settings=Settings(),
        policies={"google_ads": _policy(), "meta_ads": _policy()},
        image=image,
        image_inspector=inspector,
        offline=True,
    )
    rendered = report_summary(report)
    assert rendered["ad"]["fixed_text"] == ("AeroBeat AB-01 is splash-resistant for everyday use.")
    assert rendered["needs_review"] is True
    assert rendered["confidence"] < 100
    assert rendered["summary"] == (
        f"Needs review: the image has {len(rendered['compliance'])} non-compliant claim(s); "
        "suggested replacement text is in fixed_text."
    )
    original_claim = report.original_audit.claims[0]
    assert rendered["compliance"] == _compliance_summary(
        _score_checks(report, report.original_audit, include_report_errors=False),
        report.original_audit,
    )
    assert any(
        f"Claim ‘{original_claim.claim}’ is contradicted:" in message
        for message in rendered["compliance"]
    )
    assert rendered["claims"] == []
    assert report.revised_audit.decision == Decision.PASS
    assert report.revised_audit.coverage.image.status == CoverageStatus.NOT_APPLICABLE
    _validate_check_payloads(report)

    with pytest.raises(CheckWorkflowError, match="safe PNG or JPEG"):
        await run_check_workflow(
            "",
            index=FakeCorpusIndex(),
            model=FakeModelClient([]),
            settings=Settings(),
            policies={"google_ads": _policy(), "meta_ads": _policy()},
            image=b"not-an-image",
            offline=True,
        )
    failure = _parse_rendered_report(
        render_generation_failure("", "bytes are not a safe PNG or JPEG image")
    )
    assert failure["needs_review"] is True
    assert failure["ad"] is None


def test_corpus_claim_extraction_prompt_uses_only_ad_text():
    request = _request("AeroBeat AB-01 is 100% waterproof.").model_copy(
        update={
            "image_observations": [
                Observation(
                    observation_id="obs-1",
                    kind=ObservationKind.VISIBLE_TEXT,
                    text="The text '100% Waterproof' is visible in the image.",
                )
            ]
        }
    )
    prompt = _claim_extraction_prompt(
        request,
        observation_text=["obs-1 (visible_text): The text '100% Waterproof' is visible."],
        source_excerpt="AeroBeat AB-01 product page title",
    )
    prompt_text = "\n".join(prompt)

    assert prompt[-1] == "AD COPY:\nAeroBeat AB-01 is 100% waterproof."
    assert "100% Waterproof" not in prompt_text
    assert "SUPPLIED SOURCE EXCERPTS" not in prompt_text
    assert "only identify a brand or matched product by name" in prompt_text
    assert "performance, prices, discounts, endorsements, and offers" in prompt_text


@pytest.mark.asyncio
async def test_corpus_image_extraction_ignores_image_claims_and_keeps_price_consistency():
    page_text = PAGE_TEXT + " Regular price $80. Current price $60."
    index = FakeCorpusIndex(page_text)
    observation_text = "Only $49 - 50% OFF!"
    request = _request("AeroBeat AB-01 headphones are completely waterproof.").model_copy(
        update={
            "image_inspection_status": InspectionStatus.COMPLETE,
            "image_observations": [
                Observation(
                    observation_id="obs-offer",
                    kind=ObservationKind.VISIBLE_TEXT,
                    text=observation_text,
                )
            ],
        }
    )
    model = CapturingFakeModelClient(
        [
            _ClaimExtraction(
                claims=[
                    _text_claim("The AeroBeat AB-01 is completely waterproof."),
                    _text_claim(
                        "The text '100% Waterproof' is visible in the image.",
                        source=ClaimSource.IMAGE,
                        observation_id="obs-offer",
                    ),
                ]
            ),
            _AssessmentOutput(
                assessments=[
                    _assessment(ClaimStatus.CONTRADICTED, "not waterproof"),
                ]
            ),
        ]
    )

    result = await verify_campaign(
        request,
        VerificationDependencies(
            http=None,  # type: ignore[arg-type]
            model=model,
            policy=_policy(),
            corpus_index=index,
        ),
    )
    extraction_prompt = "\n".join(str(part) for part in model.prompts[0][1])

    assert "visible in the image" not in extraction_prompt
    assert observation_text not in extraction_prompt
    assert [claim.claim for claim in result.claims if claim.id.startswith("claim-")] == [
        "The AeroBeat AB-01 is completely waterproof."
    ]
    assert not any("visible in the image" in claim.claim for claim in result.claims)
    assert sum(issue.subtype == "IMAGE_OFFER_MISMATCH" for issue in result.issues) == 1


@pytest.mark.asyncio
async def test_product_identity_can_be_supported_by_matched_page_title():
    index = FakeCorpusIndex()
    index.chunk = CorpusChunk(
        index.chunk.chunk_id,
        index.chunk.doc_id,
        index.chunk.title,
        index.chunk.heading,
        index.chunk.url,
        f"{index.document.title}\n{index.chunk.text}",
        index.chunk.sha256,
    )
    model = CapturingFakeModelClient(
        [
            _ClaimExtraction(
                claims=[_text_claim("The product is named AeroBeat AB-01.")],
            ),
            _AssessmentOutput(
                assessments=[
                    _Assessment(
                        claim_id="claim-1",
                        status=ClaimStatus.SUPPORTED,
                        source_index=1,
                        quote="AeroBeat AB-01",
                        explanation="The matched product page title names the product.",
                    )
                ]
            ),
        ]
    )

    result = await verify_campaign(
        _request("AeroBeat AB-01 headphones."),
        VerificationDependencies(
            http=None,  # type: ignore[arg-type]
            model=model,
            policy=_policy(),
            corpus_index=index,
        ),
    )

    assert result.claims[0].status == ClaimStatus.SUPPORTED
    assert any(item.excerpt == "AeroBeat AB-01" for item in result.evidence)
    assessment_prompt = "\n".join(str(part) for part in model.prompts[1][1])
    assert "product-page title or a direct line naming the product" in assessment_prompt
