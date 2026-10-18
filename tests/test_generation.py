from datetime import UTC, datetime, timedelta

import pytest

from adproof.generator.generator import (
    GeneratedGoogleAd,
    _violations,
    generate_ad,
    parse_generation_request,
)
from adproof.model_client import FakeModelClient, ModelClientError
from adproof.rag.chunker import CorpusChunk, CorpusDocument


class FakeIndex:
    def __init__(self, chunks=None):
        self.chunks = chunks or [
            CorpusChunk(
                "ab01#1",
                "aerobeat-ab01-product",
                "AeroBeat AB-01",
                "Features",
                "https://aerobeat.example/products/ab-01",
                "AeroBeat AB-01 costs $60, 25% off. Up to 30 hours.",
                "sha",
            )
        ]

    def retrieve(self, _query, *, top_k):
        return self.chunks[:top_k]

    def documents(self):
        return [
            CorpusDocument(
                "aerobeat-ab01-product",
                "AeroBeat AB-01",
                "https://aerobeat.example/products/ab-01",
                "product_page",
                "Synthetic product page",
                "sha",
            )
        ]


def _ad(**overrides):
    value = {
        "headlines": ["AeroBeat AB-01", "Up to 30 hours", "Save 25% today"],
        "descriptions": ["Get AeroBeat AB-01 for $60.", "Wireless listening for everyday use."],
        "final_url": "https://aerobeat.example/products/ab-01",
        "sources": ["ab01#1"],
    }
    value.update(overrides)
    return value


def test_parser_defaults_aliases_and_minors():
    assert parse_generation_request("AB-01").platform == "google_ads"
    assert parse_generation_request("Facebook AeroBeat").platform == "meta_ads"
    assert parse_generation_request("Instagram AeroBeat").platform == "meta_ads"
    assert parse_generation_request("Meta AeroBeat").platform == "meta_ads"
    assert parse_generation_request("AB-01 for teens").audience == "minors"
    assert parse_generation_request("AB-01 for students in high school").audience == "minors"


def test_google_rsa_character_limits_are_deterministic():
    ad = GeneratedGoogleAd.model_validate(_ad(headlines=["x" * 31, "ok", "ok"]))
    violations = _violations(
        ad,
        parse_generation_request("AB-01"),
        FakeIndex().chunks,
        "https://aerobeat.example/products/ab-01",
    )
    assert any("30 characters" in violation for violation in violations)


@pytest.mark.asyncio
async def test_invented_number_retries_once_then_returns_typed_error():
    model = FakeModelClient(
        [
            _ad(
                headlines=["AeroBeat", "Up to 48 hours", "Save 25%"],
            ),
            _ad(headlines=["AeroBeat", "Up to 48 hours", "Save 25%"]),
        ]
    )
    with pytest.raises(ModelClientError) as error:
        await generate_ad(
            "Generate an ad for AeroBeat AB-01",
            index=FakeIndex(),
            model=model,
            deadline=datetime.now(UTC) + timedelta(minutes=1),
        )
    assert len(model.calls) == 2
    assert error.value.error.code.value == "MODEL_MALFORMED_OUTPUT"


@pytest.mark.asyncio
async def test_cited_chunk_that_was_not_retrieved_is_rejected():
    model = FakeModelClient([_ad(sources=["not-retrieved"]), _ad(sources=["not-retrieved"])])
    with pytest.raises(ModelClientError):
        await generate_ad(
            "Generate an ad for AeroBeat AB-01",
            index=FakeIndex(),
            model=model,
            deadline=datetime.now(UTC) + timedelta(minutes=1),
        )


@pytest.mark.asyncio
async def test_generation_requires_a_product_match_from_retrieved_chunks():
    class GeneralIndex(FakeIndex):
        def __init__(self):
            self.chunks = [
                CorpusChunk(
                    "overview#1",
                    "company-overview",
                    "AeroBeat company overview",
                    "Company",
                    "https://aerobeat.example/about",
                    "AeroBeat designs consumer audio products.",
                    "overview-sha",
                )
            ]

        def documents(self):
            return [
                CorpusDocument(
                    "company-overview",
                    "AeroBeat company overview",
                    "https://aerobeat.example/about",
                    "company_overview",
                    "Synthetic company overview",
                    "overview-sha",
                )
            ]

    with pytest.raises(ModelClientError) as error:
        await generate_ad(
            "Generate an ad",
            index=GeneralIndex(),
            model=FakeModelClient([]),
            deadline=datetime.now(UTC) + timedelta(minutes=1),
        )

    assert "AB-01, AB-02 Pro, or Mini speaker" in error.value.error.message


@pytest.mark.asyncio
async def test_generation_prompt_includes_brand_chunks_and_us_policy_guidance():
    brand_chunk = CorpusChunk(
        "brand-voice#1",
        "aerobeat-brand-voice",
        "AeroBeat brand voice",
        "Voice",
        "https://aerobeat.example/brand/voice",
        "Use clear, direct, helpful language.",
        "brand-sha",
    )

    class GuidedIndex(FakeIndex):
        def documents(self):
            return [
                *super().documents(),
                CorpusDocument(
                    "aerobeat-brand-voice",
                    "AeroBeat brand voice",
                    "https://aerobeat.example/brand/voice",
                    "brand_guidance",
                    "Synthetic brand guidelines",
                    "brand-document-sha",
                ),
            ]

        def chunks_for_documents(self, _doc_ids):
            return [brand_chunk]

    class CapturingModel(FakeModelClient):
        def __init__(self):
            super().__init__([_ad()])
            self.prompt = ""

        async def generate_json(self, prompt_parts, schema, *, deadline, purpose):
            self.prompt = "\n".join(str(part) for part in prompt_parts)
            return await super().generate_json(
                prompt_parts,
                schema,
                deadline=deadline,
                purpose=purpose,
            )

    model = CapturingModel()
    await generate_ad(
        "Generate a Google Ads ad for AeroBeat AB-01",
        index=GuidedIndex(),
        model=model,
        deadline=datetime.now(UTC) + timedelta(minutes=1),
    )

    assert "POLICY GUIDANCE" in model.prompt
    assert "FTC_DECEPTIVE_PRICING_FORMER_PRICE_REFERENCE" in model.prompt
    assert "brand-voice#1" in model.prompt


@pytest.mark.asyncio
async def test_brand_guidance_numbers_and_citations_count_as_generation_grounding():
    brand_chunk = CorpusChunk(
        "brand-voice#1",
        "aerobeat-brand-voice",
        "AeroBeat brand voice",
        "Voice",
        "https://aerobeat.example/brand/voice",
        "A synthetic brand guideline suggests a 3-step setup.",
        "brand-sha",
    )

    class GuidedIndex(FakeIndex):
        def documents(self):
            return [
                *super().documents(),
                CorpusDocument(
                    "aerobeat-brand-voice",
                    "AeroBeat brand voice",
                    "https://aerobeat.example/brand/voice",
                    "brand_guidance",
                    "Synthetic brand guidelines",
                    "brand-document-sha",
                ),
            ]

        def chunks_for_documents(self, _doc_ids):
            return [brand_chunk]

    model = FakeModelClient(
        [
            _ad(
                headlines=["AeroBeat AB-01", "3-step setup", "Save 25% today"],
                sources=["brand-voice#1"],
            )
        ]
    )
    result = await generate_ad(
        "Generate an ad for AeroBeat AB-01",
        index=GuidedIndex(),
        model=model,
        deadline=datetime.now(UTC) + timedelta(minutes=1),
    )

    assert result["generated_ad"]["sources"] == ["brand-voice#1"]
    assert any(source["chunk_id"] == "brand-voice#1" for source in result["sources"])
    assert len(model.calls) == 1


@pytest.mark.asyncio
async def test_policy_guidance_numbers_do_not_authorize_product_claims(monkeypatch):
    from adproof.generator import generator

    monkeypatch.setattr(generator, "_policy_guidance", lambda _request: "Policy number 8675309.")
    unsupported = _ad(headlines=["AeroBeat AB-01", "8675309 benefits", "Save 25% today"])
    model = FakeModelClient([unsupported, unsupported])

    with pytest.raises(ModelClientError) as error:
        await generate_ad(
            "Generate an ad for AeroBeat AB-01",
            index=FakeIndex(),
            model=model,
            deadline=datetime.now(UTC) + timedelta(minutes=1),
        )

    attempts = error.value.error.details["attempt_violations"]
    assert len(attempts) == 2
    assert all(any("8675309" in violation for violation in attempt) for attempt in attempts)
