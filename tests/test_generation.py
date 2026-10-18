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
