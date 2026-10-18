from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from adproof.check_workflow import CheckWorkflowError, run_check_workflow
from adproof.domain.models import ObservationKind, TypedError, TypedErrorCode
from adproof.infrastructure.budget import ModelCallBudget
from adproof.infrastructure.settings import Settings
from adproof.inspector.inspector import ImageInspector
from adproof.model_client import FakeModelClient, ModelClientError, build_model_client
from adproof.orchestrator.report_view import render_generation_failure, render_report
from adproof.rag.index import CorpusIndex
from adproof.verifier.policy import PolicyEngine
from adproof.verifier.verifier import _AssessmentOutput

ROOT = Path(__file__).resolve().parents[1]


def _policies() -> dict[str, PolicyEngine]:
    catalog = ROOT / "data/policies/catalog.json"
    packs = ROOT / "data/policies/packs"
    return {
        "google_ads": PolicyEngine.from_files(catalog, packs / "google_ads_us_electronics_v1.json"),
        "meta_ads": PolicyEngine.from_files(catalog, packs / "meta_ads_us_electronics_v1.json"),
    }


def _offline_model(image: bool) -> FakeModelClient:
    from adproof.inspector.inspector import _InspectionOutput

    responses = []
    if image:
        responses.append(
            _InspectionOutput(
                observations=[
                    {
                        "kind": ObservationKind.VISIBLE_TEXT.value,
                        "text": "AeroBeat AB-01 headphones",
                    }
                ],
                readable=True,
            ).model_dump()
        )
    responses.extend(
        [
            ModelClientError(
                TypedError(
                    code=TypedErrorCode.MODEL_UNAVAILABLE,
                    message="Offline fake models cannot verify this ad.",
                )
            ),
            _AssessmentOutput(assessments=[]).model_dump(),
        ]
    )
    return FakeModelClient(responses, model_version="offline-check")


async def _run(text: str, image_path: str | None, offline: bool) -> int:
    try:
        image = Path(image_path).read_bytes() if image_path else None
        settings = Settings.from_env()
        index = CorpusIndex()
        index.ensure_built()
        model = (
            _offline_model(image is not None)
            if offline
            else build_model_client(settings, ModelCallBudget(limit=40))
        )
        report = await run_check_workflow(
            text,
            index=index,
            model=model,
            settings=settings,
            policies=_policies(),
            image=image,
            image_inspector=ImageInspector(model),
            offline=offline,
        )
        print(render_report(report))
    except CheckWorkflowError as exc:
        print(render_generation_failure(text, str(exc)))
    except ModelClientError as exc:
        print(render_generation_failure(text, exc.error.message))
    except Exception:
        message = (
            "Image could not be processed safely."
            if image_path
            else "Ad check could not be processed."
        )
        print(render_generation_failure(text, message))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Check an ad against company data and policies")
    parser.add_argument("--image")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("text", nargs="*")
    args = parser.parse_args()
    return asyncio.run(_run(" ".join(args.text), args.image, args.offline))


if __name__ == "__main__":
    raise SystemExit(main())
