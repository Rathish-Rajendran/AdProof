from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import sentry_sdk

from adproof.domain.models import CampaignInput, ExecutionMode
from adproof.infrastructure.budget import ModelCallBudget
from adproof.infrastructure.image import freeze_image
from adproof.infrastructure.safe_http import SafeHttpClient
from adproof.infrastructure.settings import Settings
from adproof.infrastructure.store import SQLiteStore
from adproof.infrastructure.telemetry import initialize_telemetry
from adproof.inspector.inspector import ImageInspector
from adproof.model_client import build_model_client
from adproof.orchestrator.gateway import LocalGateway
from adproof.orchestrator.workflow import WorkflowDependencies, run_campaign
from adproof.verifier.policy import PolicyEngine
from adproof.verifier.verifier import VerificationDependencies

ROOT = Path(__file__).resolve().parents[1]


async def live_smoke(max_model_calls: int) -> int:
    settings = Settings.from_env()
    initialize_telemetry(settings, role="live-smoke")
    budget = ModelCallBudget(max_model_calls)
    model = build_model_client(settings, budget)
    inspector = ImageInspector(model)
    inspections = []
    image_names = (
        "aerobeat-neutral.png",
        "aerobeat-only49.png",
        "aerobeat-blurry.png",
    )
    deadline = datetime.now(UTC) + timedelta(seconds=settings.workflow_deadline_seconds)
    for name in image_names:
        path = ROOT / "data/fixtures/public" / name
        frozen = freeze_image(path.read_bytes())
        result = await inspector.inspect(
            candidate_id=name,
            image_sha256=frozen.model_input_sha256,
            image_bytes=frozen.model_input,
            deadline=deadline,
        )
        inspections.append(
            {
                "fixture": name,
                "model_spec": settings.model_spec_for("image_inspection"),
                "status": result.status.value,
                "model_version": result.model_version,
                "observations": [item.model_dump(mode="json") for item in result.observations],
                "errors": [error.model_dump(mode="json") for error in result.errors],
            }
        )

    campaign_path = ROOT / "data/fixtures/demo_campaign.json"
    campaign = CampaignInput.model_validate_json(campaign_path.read_text(encoding="utf-8"))
    if (
        "REPLACE_COMMIT_SHA" in campaign.creative.image_url
        or "REPLACE_COMMIT_SHA" in campaign.landing_page_url
    ):
        e2e = {
            "status": "SKIPPED",
            "reason": "demo fixture URLs have not been pinned to a pushed commit",
        }
    else:
        policy = PolicyEngine.from_files(
            ROOT / "data/policies/catalog.json",
            ROOT / "data/policies/packs/google_ads_us_electronics_v1.json",
        )
        http = SafeHttpClient()
        verification = VerificationDependencies(http=http, model=model, policy=policy)
        dependencies = WorkflowDependencies(
            http=http,
            inspector=inspector,
            gateway=LocalGateway(verification, model),
            store=SQLiteStore(settings.runtime_dir / "live-smoke.sqlite3"),
            budget=budget,
            settings=settings,
            execution_mode=ExecutionMode.LIVE,
        )
        trace_id = None
        with sentry_sdk.start_transaction(name="adproof live smoke", op="adproof.live_smoke"):
            trace_id = sentry_sdk.get_traceparent()
            report = await run_campaign(
                campaign,
                owner="live-smoke",
                session_id="live-smoke",
                dependencies=dependencies,
            )
        e2e = {
            "status": "COMPLETED",
            "audit_id": report.audit_id,
            "decision": report.final_decision.value,
            "workflow_status": report.workflow_status.value,
            "model_versions": report.model_versions,
            "model_specs": report.model_specs,
            "trace_parent": trace_id,
            "errors": [error.model_dump(mode="json") for error in report.errors],
        }
        await http.close()
    result = {
        "model_provider": settings.model_provider,
        "configured_model": settings.active_model,
        "model_specs": settings.model_specs,
        "model_calls_used": budget.consumed,
        "model_call_limit": max_model_calls,
        "calls": model.call_records,
        "image_inspections": inspections,
        "end_to_end": e2e,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Opt-in live model image/JSON smoke tests.")
    parser.add_argument("--max-model-calls", type=int, default=20)
    args = parser.parse_args()
    if args.max_model_calls < 1 or args.max_model_calls > 20:
        parser.error("--max-model-calls must be in the range 1..20")
    print("WARNING: this command performs live model inference; no fixture fallback is used.")
    return asyncio.run(live_smoke(args.max_model_calls))


if __name__ == "__main__":
    raise SystemExit(main())
