"""Synthetic inputs. Nothing here is fetched from a real advertiser."""

from copy import deepcopy

from .errors import DemoError


UNSAFE_COPY = (
    "Lose 20 pounds in two weeks—clinically proven. "
    "Recommended by doctors. Today only: 50% off."
)
SAFE_COPY = "Acme Balance. $39.99, previously $49.99."
LANDING = {
    "product": "Acme Balance",
    "current_price": 39.99,
    "previous_price": 49.99,
    "text": "Acme Balance. Current price: $39.99. Previous price: $49.99. "
    "This fictional page supplies no clinical study or doctor endorsement.",
    "source_url": "/fixture/acme-balance",
}


def _campaign(image="neutral", copy=UNSAFE_COPY):
    return {
        "schema_version": "1.0",
        "creative": {
            "format": "IMAGE",
            "image_url": f"/static/creatives/{image}.svg",
            "ad_copy": copy,
        },
        "landing_page_url": "fixture://acme-balance",
        "campaign": {
            "platform": "GOOGLE_ADS",
            "jurisdiction": "US",
            "audience": "Adults in the United States",
            "category": "HEALTH_WELLNESS",
        },
        "evidence_documents": [],
    }


_SCENARIOS = [
    {
        "id": "copy_repair",
        "name": "Repair unsafe copy",
        "description": "Unsupported claims in the copy; a neutral product image can stay.",
        "expected": "BLOCK → PASS",
        "campaign": _campaign(),
        "behavior": "normal",
    },
    {
        "id": "unsafe_image",
        "name": "Image stays blocked",
        "description": "The same claims are embedded in the image. A text rewrite cannot remove them.",
        "expected": "BLOCK → BLOCK",
        "campaign": _campaign("unsafe"),
        "behavior": "normal",
    },
    {
        "id": "verifier_timeout",
        "name": "Verifier unavailable",
        "description": "The verifier times out twice. Retry once, then ask for human review.",
        "expected": "HUMAN_REVIEW",
        "campaign": _campaign(),
        "behavior": "verifier_timeout",
    },
    {
        "id": "reverification_timeout",
        "name": "Re-audit fails",
        "description": "Original risk is known, but the repaired candidate cannot be verified.",
        "expected": "BLOCK preserved",
        "campaign": _campaign(),
        "behavior": "reverification_timeout",
    },
    {
        "id": "transient_retry",
        "name": "Recover after a retry",
        "description": "One transient verifier failure, followed by a successful full audit.",
        "expected": "RETRY → PASS",
        "campaign": _campaign(),
        "behavior": "transient_retry",
    },
    {
        "id": "safe_campaign",
        "name": "Already safe",
        "description": "Supported product prices. The orchestrator skips unnecessary repair.",
        "expected": "PASS · no repair",
        "campaign": _campaign(copy=SAFE_COPY),
        "behavior": "normal",
    },
]


def list_scenarios():
    return deepcopy(_SCENARIOS)


def get_scenario(scenario_id):
    for scenario in _SCENARIOS:
        if scenario["id"] == scenario_id:
            return deepcopy(scenario)
    raise DemoError("UNKNOWN_SCENARIO", "Choose one of the provided demo scenarios.", 404)
