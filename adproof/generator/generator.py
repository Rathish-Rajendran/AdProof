from __future__ import annotations

import re
from datetime import datetime
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
    product_query: str = Field(min_length=1, max_length=2048)
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
        product_query=text.strip(),
        platform=platform,
        audience=audience,
    )


def _document_for_request(index: Any, request: GenerationRequest):
    documents = index.documents()
    query_tokens = set(re.findall(r"[a-z0-9]+", request.product_query.casefold()))
    candidates = [document for document in documents if document.doc_type == "product_page"]
    return max(
        candidates,
        key=lambda document: len(
            query_tokens & set(re.findall(r"[a-z0-9]+", document.title.casefold()))
        ),
        default=None,
    )


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
    chunks = index.retrieve(request.product_query, top_k=6)
    product = _document_for_request(index, request)
    if not chunks or product is None:
        raise ModelClientError(
            TypedError(
                code=TypedErrorCode.SOURCE_UNAVAILABLE,
                message="No matching product page or corpus chunks were retrieved.",
            )
        )
    schema = GeneratedGoogleAd if request.platform == "google_ads" else GeneratedMetaAd
    prompt = [
        "Generate advertising copy grounded only in the supplied synthetic company-corpus chunks. "
        "Do not infer unsupported product facts. Cite retrieved chunk IDs in sources. "
        f"Use final_url exactly as {product.url}.",
        "REQUEST:\n" + request.model_dump_json(),
        "RETRIEVED CHUNKS:\n" + "\n\n".join(f"{chunk.chunk_id}: {chunk.text}" for chunk in chunks),
        (
            "For Google Ads, provide 3-5 headlines of at most 30 characters and exactly 2 "
            "descriptions of at most 90 characters."
            if schema is GeneratedGoogleAd
            else "For Meta, provide primary_text and headline."
        ),
    ]
    for attempt in range(2):
        response = await model.generate_json(
            prompt,
            schema,
            deadline=deadline,
            purpose="ad_generation",
        )
        ad = response.data
        violations = _violations(ad, request, chunks, product.url)
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
                    for chunk in chunks
                ],
            }
        if attempt == 0:
            prompt.append("Correct these deterministic violations:\n" + "\n".join(violations))
    raise ModelClientError(
        TypedError(
            code=TypedErrorCode.MODEL_MALFORMED_OUTPUT,
            message="Generated ad failed deterministic validation after one correction retry.",
        )
    )
