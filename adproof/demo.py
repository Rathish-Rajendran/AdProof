from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from adproof.domain.models import CampaignInput, ExecutionMode
from adproof.infrastructure.budget import ModelCallBudget
from adproof.infrastructure.safe_http import FetchedSource
from adproof.infrastructure.settings import Settings
from adproof.infrastructure.store import SQLiteStore
from adproof.inspector.inspector import ImageInspector, _InspectionOutput
from adproof.model_client import FakeModelClient
from adproof.orchestrator.gateway import LocalGateway
from adproof.orchestrator.workflow import WorkflowDependencies, run_campaign
from adproof.verifier.policy import PolicyEngine
from adproof.verifier.verifier import (
    VerificationDependencies,
    _Assessment,
    _AssessmentOutput,
    _ClaimExtraction,
    _ExtractedClaim,
)


class FixtureHttpClient:
    def __init__(self, root: Path):
        self.root = root

    async def fetch(self, url: str, *, max_bytes: int) -> FetchedSource:
        path = urlsplit(url).path
        name = Path(path).name
        fixture_path = self.root / "data/fixtures/public" / name
        content = fixture_path.read_bytes()
        if len(content) > max_bytes:
            raise ValueError("fixture exceeds requested byte limit")
        content_type = "image/png" if name.endswith(".png") else "text/html; charset=utf-8"
        return FetchedSource(
            url=url,
            status_code=200,
            headers={"content-type": content_type},
            content=content,
        )

    async def close(self) -> None:
        return None


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


async def run_mock(*, repair: bool = False) -> int:
    root = _root()
    campaign_data = json.loads(
        (root / "data/fixtures/demo_campaign.json").read_text(encoding="utf-8")
    )
    campaign_data["creative"]["image_url"] = "mock://fixtures/aerobeat-neutral.png"
    campaign_data["landing_page_url"] = "mock://fixtures/aerobeat.html"
    campaign_data["request_id"] = f"mock-aerobeat-{uuid.uuid4().hex}"
    campaign_data["repair_mode"] = "repair_once" if repair else "audit_only"
    campaign = CampaignInput.model_validate(campaign_data)
    client = FakeModelClient(
        [
            _InspectionOutput(observations=[], readable=True),
            _ClaimExtraction(
                claims=[
                    _ExtractedClaim(
                        claim="AeroBeat headphones are completely waterproof.",
                        source="ad_text",
                        claim_type="performance",
                    ),
                    _ExtractedClaim(
                        claim="Get 48-hour battery life with noise cancellation off.",
                        source="ad_text",
                        claim_type="quantitative_specification",
                        conditions={"noise_cancellation": "off"},
                    ),
                    _ExtractedClaim(
                        claim="Recommended by 1,000 athletes.",
                        source="ad_text",
                        claim_type="endorsement",
                    ),
                    _ExtractedClaim(
                        claim="Now $60.",
                        source="ad_text",
                        claim_type="price",
                    ),
                    _ExtractedClaim(
                        claim="50% off",
                        source="ad_text",
                        claim_type="discount",
                    ),
                ],
                ignored_statements=[],
            ),
            _AssessmentOutput(
                assessments=[
                    _Assessment(
                        claim_id="claim-1",
                        status="CONTRADICTED",
                        source_index=0,
                        quote="not waterproof",
                        explanation="The product page says not waterproof.",
                    ),
                    _Assessment(
                        claim_id="claim-2",
                        status="CONTRADICTED",
                        source_index=0,
                        quote="Up to 30 hours of battery life with noise cancellation off.",
                        explanation="The page states up to 30 hours, not 48 hours.",
                    ),
                    _Assessment(
                        claim_id="claim-3",
                        status="INSUFFICIENT_EVIDENCE",
                        explanation="No independent athlete endorsement is supplied.",
                    ),
                    _Assessment(
                        claim_id="claim-4",
                        status="SUPPORTED",
                        source_index=0,
                        quote="Current price $60.",
                        explanation="The page lists $60 as the current price.",
                    ),
                    _Assessment(
                        claim_id="claim-5",
                        status="SUPPORTED",
                        source_index=0,
                        quote="Regular price $80. Current price $60.",
                        explanation="The page lists the labeled original and current prices.",
                    ),
                ]
            ),
        ]
    )
    http = FixtureHttpClient(root)
    policy = PolicyEngine.from_files(
        root / "data/policies/catalog.json",
        root / "data/policies/packs/google_ads_us_electronics_v1.json",
    )
    budget = ModelCallBudget(20)
    dependencies = WorkflowDependencies(
        http=http,  # type: ignore[arg-type]
        inspector=ImageInspector(client),
        gateway=LocalGateway(
            VerificationDependencies(http=http, model=client, policy=policy), client
        ),
        store=SQLiteStore(root / "runtime/mock-demo.sqlite3"),
        budget=budget,
        settings=Settings(runtime_dir=root / "runtime"),
        execution_mode=ExecutionMode.MOCK,
    )
    report = await run_campaign(
        campaign,
        owner="mock-user",
        session_id="mock-session",
        dependencies=dependencies,
    )
    print("EXECUTION_MODE=MOCK — synthetic fixtures and fake model responses; no live inference.")
    print(report.model_dump_json(indent=2))
    await http.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Explicit offline MOCK demonstration.")
    parser.add_argument("--mode", choices=["mock"], required=True)
    parser.add_argument("--repair", action="store_true")
    args = parser.parse_args()
    return asyncio.run(run_mock(repair=args.repair))


if __name__ == "__main__":
    raise SystemExit(main())
