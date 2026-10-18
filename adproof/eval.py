from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from adproof.domain.models import CampaignInput, ExecutionMode
from adproof.infrastructure.budget import ModelCallBudget
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
CASE_FILES = {
    1: "case01_unsafe_neutral.json",
    2: "case02_supported_neutral.json",
    3: "case03_unsafe_only49.json",
    4: "case04_correct_neutral.json",
}
EXPECTED_DECISIONS = {
    1: "FIX_REQUIRED",
    2: "PASS",
    3: "FIX_REQUIRED",
    4: "PASS",
}


def _reported_model_versions(calls: list[dict[str, Any]]) -> list[str]:
    return sorted(
        {
            str(call["reported_model_version"])
            for call in calls
            if call.get("reported_model_version") and not call.get("error")
        }
    )


async def run_live_evaluation(case_numbers: list[int], max_model_calls: int) -> dict[str, Any]:
    settings = Settings.from_env()
    initialize_telemetry(settings, role="evaluation")
    budget = ModelCallBudget(max_model_calls)
    model = build_model_client(settings, budget)
    inspector = ImageInspector(model)
    policy = PolicyEngine.from_files(
        ROOT / "data/policies/catalog.json",
        ROOT / "data/policies/packs/google_ads_us_electronics_v1.json",
    )
    http = SafeHttpClient()
    verification = VerificationDependencies(http=http, model=model, policy=policy)
    results = []
    run_id = uuid.uuid4().hex
    try:
        for case_number in case_numbers:
            if budget.consumed >= max_model_calls:
                results.append(
                    {
                        "case": case_number,
                        "model_provider": settings.model_provider,
                        "configured_model": settings.active_model,
                        "expected_decision": EXPECTED_DECISIONS[case_number],
                        "actual_decision": "SKIPPED",
                        "skip_reason": "shared model-call budget exhausted",
                        "reported_model_versions": [],
                        "calls": [],
                    }
                )
                continue
            campaign_path = ROOT / "data/fixtures/cases" / CASE_FILES[case_number]
            campaign = CampaignInput.model_validate_json(
                campaign_path.read_text(encoding="utf-8")
            ).model_copy(
                update={
                    "request_id": f"eval-{run_id}-case-{case_number}",
                }
            )
            call_start = len(model.call_records)
            started = datetime.now(UTC)
            case_store = SQLiteStore(
                settings.runtime_dir / "eval" / f"{run_id}-case-{case_number}.sqlite3"
            )
            dependencies = WorkflowDependencies(
                http=http,
                inspector=inspector,
                gateway=LocalGateway(verification, model),
                store=case_store,
                budget=budget,
                settings=settings,
                execution_mode=ExecutionMode.LIVE,
            )
            try:
                report = await run_campaign(
                    campaign,
                    owner=f"eval-{run_id}",
                    session_id=f"case-{case_number}",
                    dependencies=dependencies,
                )
                claims = report.original_audit.claims if report.original_audit else []
                evidence = report.original_audit.evidence if report.original_audit else []
                evidence_ids = {item.id for item in evidence}
                case_calls = model.call_records[call_start:]
                results.append(
                    {
                        "case": case_number,
                        "model_provider": settings.model_provider,
                        "configured_model": settings.active_model,
                        "expected_decision": EXPECTED_DECISIONS[case_number],
                        "actual_decision": report.final_decision.value,
                        "workflow_status": report.workflow_status.value,
                        "claim_statuses": {claim.claim: claim.status.value for claim in claims},
                        "arithmetic": {
                            claim.claim: claim.derivation for claim in claims if claim.derivation
                        },
                        "evidence_ids_valid": all(
                            evidence_id in evidence_ids
                            for claim in claims
                            for evidence_id in claim.evidence_ids
                        ),
                        "model_versions": report.model_versions,
                        "reported_model_versions": _reported_model_versions(case_calls),
                        "model_call_count": len(case_calls),
                        "calls": case_calls,
                        "timings_seconds": {
                            "workflow": report.timings.get("total_seconds"),
                            "wall": (datetime.now(UTC) - started).total_seconds(),
                        },
                        "errors": [error.model_dump(mode="json") for error in report.errors],
                    }
                )
            except Exception as exc:
                case_calls = model.call_records[call_start:]
                results.append(
                    {
                        "case": case_number,
                        "model_provider": settings.model_provider,
                        "configured_model": settings.active_model,
                        "expected_decision": EXPECTED_DECISIONS[case_number],
                        "actual_decision": "ERROR",
                        "error_type": type(exc).__name__,
                        "reported_model_versions": _reported_model_versions(case_calls),
                        "model_call_count": len(case_calls),
                        "calls": case_calls,
                    }
                )
    finally:
        await http.close()
    result = {
        "run_id": run_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "model_provider": settings.model_provider,
        "configured_model": settings.active_model,
        "reported_model_versions": sorted(
            {version for result in results for version in result.get("reported_model_versions", [])}
        ),
        "model_call_budget": max_model_calls,
        "model_calls_used": budget.consumed,
        "sample_size": len(results),
        "results": results,
    }
    output = settings.runtime_dir / "eval" / f"{run_id}.json"
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return {"report": result, "output_path": str(output)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Opt-in, bounded live evaluation.")
    parser.add_argument("--live", action="store_true", help="run the configured live model")
    parser.add_argument("--cases", default="1,2,3,4")
    parser.add_argument("--max-model-calls", type=int, default=20)
    args = parser.parse_args()
    if not args.live:
        parser.error("pass --live to enable live model inference")
    if not 1 <= args.max_model_calls <= 40:
        parser.error("--max-model-calls must be in the range 1..40")
    try:
        case_numbers = [int(value) for value in args.cases.split(",")]
    except ValueError:
        parser.error("--cases must be a comma-separated list of case numbers")
    if not case_numbers or any(number not in CASE_FILES for number in case_numbers):
        parser.error("--cases supports only case numbers 1 through 4")
    result = asyncio.run(run_live_evaluation(case_numbers, args.max_model_calls))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
