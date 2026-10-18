from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from adproof.domain.models import TypedError, TypedErrorCode
from adproof.infrastructure.numbers import number_tokens
from adproof.model_client import ModelClient, ModelClientError

MINOR_TERMS = re.compile(
    r"\b(?:teen|teens|kids|children|child|under\s+18|students\s+in\s+high\s+school)\b",
    re.IGNORECASE,
)
META_TERMS = re.compile(r"\b(?:meta|facebook|instagram)\b", re.IGNORECASE)


class GenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str = Field(max_length=2048)
    platform: str = "google_ads"
    jurisdiction: str = "US"
    language: str = "en"
    audience: str = "adults"


class GenerationTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    audit_id: str
    request_id: str
    campaign_id: str
    candidate_id: str
    creative_version: int = 1
    prompt: str
    deadline: datetime


class GenerationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request: dict[str, Any]
    generated_ad: dict[str, Any]
    model_version: str
    sources: list[dict[str, str]]


class GeneratedGoogleAd(BaseModel):
    model_config = ConfigDict(extra="forbid")
    headlines: list[str] = Field(min_length=3, max_length=5)
    descriptions: list[str] = Field(min_length=2, max_length=2)
    final_url: str
    sources: list[str] = Field(default_factory=list)


class GeneratedMetaAd(BaseModel):
    model_config = ConfigDict(extra="forbid")
    primary_text: str
    headline: str
    final_url: str
    sources: list[str] = Field(default_factory=list)


def parse_generation_request(text: str) -> GenerationRequest:
    platform = "meta_ads" if META_TERMS.search(text) else "google_ads"
    audience = "minors" if MINOR_TERMS.search(text) else "adults"
    return GenerationRequest(
        prompt=text.strip(),
        platform=platform,
        audience=audience,
    )


def _document_for_request(index: Any, chunks):
    documents = index.documents()
    by_id = {document.doc_id: document for document in documents}
    for chunk in chunks:
        owner = by_id.get(chunk.doc_id)
        if owner is None or not owner.product_id and owner.doc_type != "product_page":
            continue
        product_id = owner.product_id or owner.doc_id
        product = next(
            (
                document
                for document in documents
                if document.doc_type == "product_page"
                and (document.product_id or document.doc_id) == product_id
            ),
            None,
        )
        if product is not None:
            return product
    return None


def _brand_chunks(index: Any) -> list[Any]:
    documents = index.documents()
    doc_ids = {
        document.doc_id
        for document in documents
        if document.doc_type in {"brand_voice", "brand_guidelines", "brand_guidance"}
    }
    if not doc_ids:
        return []
    if hasattr(index, "chunks_for_documents"):
        return index.chunks_for_documents(doc_ids)
    candidates = index.retrieve("AeroBeat brand voice guidelines", top_k=32)
    return [chunk for chunk in candidates if chunk.doc_id in doc_ids]


def _policy_guidance(request: GenerationRequest) -> str:
    library = Path(__file__).resolve().parents[2] / "data" / "policies" / "library"
    sections = []
    for path in sorted(library.glob("*.json")):
        for entry in json.loads(path.read_text(encoding="utf-8")):
            if (
                entry.get("platform") in {request.platform, "any"}
                and entry.get("jurisdiction") == request.jurisdiction
                and entry.get("excerpts")
            ):
                excerpts = "\n".join(f"- {excerpt}" for excerpt in entry["excerpts"])
                sections.append(f"{entry['policy_id']}:\n{excerpts}")
    return "\n\n".join(sections)


def _violations(ad: BaseModel, request: GenerationRequest, chunks, landing_url: str) -> list[str]:
    issues: list[str] = []
    if ad.final_url != landing_url:
        issues.append("final_url must exactly match the retrieved product landing-page URL")
    retrieved_ids = {chunk.chunk_id for chunk in chunks}
    unknown_ids = sorted(set(ad.sources) - retrieved_ids)
    if unknown_ids:
        issues.append(f"sources cite chunk IDs that were not retrieved: {unknown_ids}")
    if not ad.sources:
        issues.append("at least one retrieved corpus chunk must be cited")
    retrieved_numbers = set()
    for chunk in chunks:
        retrieved_numbers.update(number_tokens(chunk.text))
    ad_text = (
        " ".join(ad.headlines + ad.descriptions)
        if isinstance(ad, GeneratedGoogleAd)
        else f"{ad.primary_text} {ad.headline}"
    )
    invented = number_tokens(ad_text) - retrieved_numbers
    if invented:
        issues.append(f"numeric tokens are not supported by retrieved chunks: {sorted(invented)}")
    if isinstance(ad, GeneratedGoogleAd):
        if not 3 <= len(ad.headlines) <= 5:
            issues.append("Google Ads requires 3-5 headlines")
        if any(len(headline) > 30 for headline in ad.headlines):
            issues.append("each Google Ads headline must be at most 30 characters")
        if len(ad.descriptions) != 2:
            issues.append("Google Ads requires exactly 2 descriptions")
        if any(len(description) > 90 for description in ad.descriptions):
            issues.append("each Google Ads description must be at most 90 characters")
    return issues


async def generate_ad(
    text: str,
    *,
    index,
    model: ModelClient,
    deadline: datetime,
) -> dict[str, Any]:
    request = parse_generation_request(text)
    retrieved_chunks = index.retrieve(request.prompt, top_k=6)
    product = _document_for_request(index, retrieved_chunks)
    if not retrieved_chunks or product is None:
        raise ModelClientError(
            TypedError(
                code=TypedErrorCode.SOURCE_UNAVAILABLE,
                message=(
                    "Please name a product so AdProof can select the right product page: "
                    "AB-01, AB-02 Pro, or Mini speaker."
                ),
            )
        )
    grounding_chunks = list(
        {chunk.chunk_id: chunk for chunk in [*retrieved_chunks, *_brand_chunks(index)]}.values()
    )
    schema = GeneratedGoogleAd if request.platform == "google_ads" else GeneratedMetaAd
    policy_guidance = _policy_guidance(request)
    prompt = [
        "Generate advertising copy grounded only in the supplied synthetic company-corpus chunks. "
        "Do not infer unsupported product facts. Cite retrieved chunk IDs in sources. "
        f"Use final_url exactly as {product.url}.",
        "REQUEST:\n" + request.model_dump_json(),
        "POLICY GUIDANCE:\n" + policy_guidance,
        "RETRIEVED CHUNKS:\n"
        + "\n\n".join(f"{chunk.chunk_id}: {chunk.text}" for chunk in grounding_chunks),
        (
            "For Google Ads, provide 3-5 headlines of at most 30 characters and exactly 2 "
            "descriptions of at most 90 characters."
            if schema is GeneratedGoogleAd
            else "For Meta, provide primary_text and headline."
        ),
    ]
    attempt_violations = []
    for attempt in range(2):
        response = await model.generate_json(
            prompt,
            schema,
            deadline=deadline,
            purpose="ad_generation",
        )
        ad = response.data
        violations = _violations(ad, request, grounding_chunks, product.url)
        if not violations:
            return {
                "request": request.model_dump(mode="json"),
                "generated_ad": ad.model_dump(mode="json"),
                "model_version": response.model_version,
                "sources": [
                    {
                        "chunk_id": chunk.chunk_id,
                        "title": chunk.title,
                        "url": chunk.url,
                    }
                    for chunk in grounding_chunks
                ],
            }
        attempt_violations.append(violations)
        if attempt == 0:
            prompt.append("Correct these deterministic violations:\n" + "\n".join(violations))
    raise ModelClientError(
        TypedError(
            code=TypedErrorCode.MODEL_MALFORMED_OUTPUT,
            message="Generated ad failed deterministic validation after one correction retry.",
            details={"attempt_violations": attempt_violations},
        )
    )
