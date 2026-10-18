from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from adproof.domain.models import (
    CampaignContext,
    ClaimSource,
    ClaimStatus,
    ClaimType,
    Decision,
    InspectionStatus,
    Phase,
    VerificationRequest,
)
from adproof.generate import _offline_model
from adproof.generator.generator import GenerationResult
from adproof.generator.workflow import run_generation_workflow
from adproof.infrastructure.settings import Settings
from adproof.model_client import FakeModelClient
from adproof.orchestrator.report_view import report_summary
from adproof.rag.chunker import CorpusChunk, CorpusDocument
from adproof.rag.index import CorpusIndex
from adproof.transport.models import SpecialistOperation, SpecialistResult, validate_result_shape
from adproof.verifier.policy import PolicyEngine
from adproof.verifier.verifier import (
    VerificationDependencies,
    _Assessment,
    _AssessmentOutput,
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
    def __init__(self):
        self.document = CorpusDocument(
            "aerobeat-ab01-product",
            "AeroBeat AB-01",
            PAGE_URL,
            "product_page",
            PAGE_TEXT,
            "document-sha",
        )
        self.chunk = CorpusChunk(
            "aerobeat-ab01-product#1",
            self.document.doc_id,
            self.document.title,
            "Product facts",
            PAGE_URL,
            PAGE_TEXT,
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
