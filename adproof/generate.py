from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from adproof.domain.models import ClaimSource, ClaimStatus, ClaimType
from adproof.generator.generator import (
    GeneratedGoogleAd,
    GeneratedMetaAd,
    parse_generation_request,
)
from adproof.generator.workflow import run_generation_workflow
from adproof.infrastructure.budget import ModelCallBudget
from adproof.infrastructure.settings import Settings
from adproof.model_client import FakeModelClient, build_model_client
from adproof.orchestrator.report_view import report_summary
from adproof.rag.index import CorpusIndex
from adproof.verifier.policy import PolicyEngine

ROOT = Path(__file__).resolve().parents[1]


def _offline_model(index: CorpusIndex, prompt: str) -> FakeModelClient:
    request = parse_generation_request(prompt)
    chunks = index.retrieve(request.product_query, top_k=6)
    product = next(
        document
        for document in index.documents()
        if document.doc_type == "product_page" and "ab01" in document.doc_id
    )
    citations = [chunk.chunk_id for chunk in chunks]
    if request.platform == "google_ads":
        generated = GeneratedGoogleAd(
            headlines=["AeroBeat AB-01", "Waterproof headphones", "Wireless sound"],
            descriptions=[
                "Meet the AeroBeat AB-01 headphones.",
                "Enjoy splash-resistant sound for everyday listening.",
            ],
            final_url=product.url,
            sources=citations,
        ).model_dump()
    else:
        generated = GeneratedMetaAd(
            primary_text="Waterproof AeroBeat AB-01 headphones.",
            headline="AeroBeat sound",
            final_url=product.url,
            sources=citations,
        ).model_dump()
    from adproof.remediator.remediator import _RepairOutput
    from adproof.verifier.verifier import _AssessmentOutput, _ClaimExtraction

    extraction_claims = [
        {
            "claim": "waterproof",
            "source": ClaimSource.AD_TEXT.value,
            "claim_type": ClaimType.OTHER_OBJECTIVE.value,
            "conditions": {},
        }
    ]
    repaired_claims = [
        {
            "claim": "splash-resistant for everyday use",
            "source": ClaimSource.AD_TEXT.value,
            "claim_type": ClaimType.OTHER_OBJECTIVE.value,
            "conditions": {},
        }
    ]
    assessments = [
        {
            "claim_id": "claim-1",
            "status": ClaimStatus.CONTRADICTED.value,
            "source_index": 1,
            "quote": "It is not waterproof",
            "explanation": "The product page states it is not waterproof.",
        }
    ]
    revised_assessments = [
        {
            "claim_id": "claim-1",
            "status": ClaimStatus.SUPPORTED.value,
            "source_index": 1,
            "quote": "splash-resistant for everyday use",
            "explanation": "The product page supports the qualified claim.",
        }
    ]
    return FakeModelClient(
        [
            generated,
            _ClaimExtraction(claims=extraction_claims).model_dump(),
            _AssessmentOutput(assessments=assessments).model_dump(),
            _RepairOutput(
                repaired_copy="AeroBeat AB-01 is splash-resistant for everyday use."
            ).model_dump(),
            _ClaimExtraction(claims=repaired_claims).model_dump(),
            _AssessmentOutput(assessments=revised_assessments).model_dump(),
        ],
        model_version="offline-fake",
    )


def _policies(platform: str):
    catalog = ROOT / "data/policies/catalog.json"
    pack = ROOT / "data/policies/packs"
    google = PolicyEngine.from_files(catalog, pack / "google_ads_us_electronics_v1.json")
    meta = PolicyEngine.from_files(catalog, pack / "meta_ads_us_electronics_v1.json")
    return {"google_ads": google, "meta_ads": meta}


async def _run(prompt: str, offline: bool):
    settings = Settings.from_env()
    index = CorpusIndex()
    index.ensure_built()
    model = (
        _offline_model(index, prompt)
        if offline
        else build_model_client(
            settings,
            ModelCallBudget(limit=40),
        )
    )
    report = await run_generation_workflow(
        prompt,
        index=index,
        model=model,
        settings=settings,
        policies=_policies("google_ads"),
        offline=offline,
    )
    print(json.dumps(report_summary(report), indent=2, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate and preflight a corpus-grounded ad")
    parser.add_argument("prompt")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    return asyncio.run(_run(args.prompt, args.offline))


if __name__ == "__main__":
    raise SystemExit(main())
