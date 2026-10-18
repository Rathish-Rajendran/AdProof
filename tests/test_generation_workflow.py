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
from adproof.generator.workflow import run_generation_workflow
from adproof.infrastructure.settings import Settings
from adproof.model_client import FakeModelClient
from adproof.orchestrator.report_view import report_summary
from adproof.rag.chunker import CorpusChunk, CorpusDocument
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


def _policy() -> PolicyEngine:
    return PolicyEngine.from_files(
        ROOT / "data/policies/catalog.json",
        ROOT / "data/policies/packs/google_ads_us_electronics_v1.json",
    )


def _request(copy: str, audience: str = "adults") -> VerificationRequest:
    return VerificationRequest(
        audit_id="audit-corpus",
        request_id="request-corpus",
        campaign_id="campaign-corpus",
        candidate_id="candidate-corpus",
        creative_version=1,
        phase=Phase.ORIGINAL,
        ad_copy=copy,
        landing_page_url=PAGE_URL,
        context=CampaignContext(
            platform="google_ads",
            jurisdiction="US",
            language="en",
            audience=audience,
            product_category="electronics",
        ),
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
        _request(copy, audience),
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
    summary = report_summary(report)
    assert report.original_audit.decision == Decision.FIX_REQUIRED
    assert report.revised_audit.decision == Decision.PASS
    assert report.repair_verified is True
    assert summary["request"]["platform"] == "google_ads"
    assert summary["request"]["prompt"] == prompt
    assert "product_query" not in summary["request"]
    assert summary["generated_ad"]["final_url"] == PAGE_URL
    assert list(summary) == [
        "audit_id",
        "request",
        "generated_ad",
        "original_check",
        "fix",
        "recheck",
        "final",
    ]
    assert set(summary) >= {
        "audit_id",
        "request",
        "generated_ad",
        "original_check",
        "fix",
        "recheck",
        "final",
    }
    assert summary["final"]["repair_verified"] is True
