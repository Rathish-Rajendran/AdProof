from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from adproof.domain import models

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas"
EXAMPLES_DIR = SCHEMA_DIR / "examples"

CAMPAIGN_INPUT_EXAMPLE = {
    "schema_version": "1.0",
    "request_id": "schema-example-1",
    "campaign_id": "aerobeat-demo",
    "creative_version": 1,
    "creative": {
        "image_url": "mock://fixtures/aerobeat-neutral.png",
        "ad_copy": "AeroBeat AB-01 headphones are splash-resistant, with up to 30 hours of battery life when noise cancellation is off.",
    },
    "landing_page_url": "mock://fixtures/aerobeat.html",
    "context": {
        "platform": "google_ads",
        "jurisdiction": "US",
        "language": "en",
        "audience": "adults",
        "product_category": "electronics",
    },
    "evidence_documents": [],
    "product_context": {"model": "AB-01", "variant": "standard", "currency": "USD", "quantity": 1},
    "repair_mode": "repair_once",
}

TYPED_ERROR_EXAMPLE = {
    "code": "MODEL_UNAVAILABLE",
    "message": "The configured model service is temporarily unavailable.",
    "retryable": True,
    "source": None,
    "details": {},
}

EXAMPLES: dict[str, dict[str, Any]] = {
    "CampaignInput": CAMPAIGN_INPUT_EXAMPLE,
    "TypedError": TYPED_ERROR_EXAMPLE,
}


def render_files() -> dict[Path, str]:
    rendered: dict[Path, str] = {}
    for name, value in vars(models).items():
        if not isinstance(value, type) or value in (BaseModel, models.StrictModel):
            continue
        if not issubclass(value, BaseModel):
            continue
        schema = value.model_json_schema()
        rendered[SCHEMA_DIR / f"{name}.schema.json"] = (
            json.dumps(schema, indent=2, sort_keys=True) + "\n"
        )
    for name, example in EXAMPLES.items():
        model = getattr(models, name)
        model.model_validate(example)
        rendered[EXAMPLES_DIR / f"{name}.json"] = (
            json.dumps(example, indent=2, sort_keys=True) + "\n"
        )
    return rendered


def main() -> int:
    for path, content in render_files().items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
