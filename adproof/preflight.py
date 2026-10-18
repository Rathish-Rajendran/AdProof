from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from adproof.domain.models import CampaignInput
from adproof.infrastructure.image import freeze_image
from adproof.infrastructure.safe_http import SafeFetchError, validate_public_url
from adproof.verifier.policy import PolicyEngine

ROOT = Path(__file__).resolve().parents[1]


async def preflight(*, offline: bool) -> int:
    required_paths = [
        ROOT / "data/policies/catalog.json",
        ROOT / "data/policies/packs/google_ads_us_electronics_v1.json",
        ROOT / "data/fixtures/public/aerobeat-neutral.png",
        ROOT / "data/fixtures/public/aerobeat-only49.png",
        ROOT / "data/fixtures/public/aerobeat-blurry.png",
        ROOT / "data/fixtures/public/aerobeat-neutral.jpg",
        ROOT / "data/fixtures/public/aerobeat.html",
    ]
    missing = [path for path in required_paths if not path.is_file()]
    if missing:
        for path in missing:
            print(f"FAIL missing: {path.relative_to(ROOT)}")
        return 1
    try:
        PolicyEngine.from_files(required_paths[0], required_paths[1])
        for image_path in required_paths[2:6]:
            frozen = freeze_image(image_path.read_bytes())
            print(f"OK image {image_path.name}: {frozen.width}x{frozen.height}")
        CampaignInput.model_validate_json(
            (ROOT / "schemas/examples/CampaignInput.json").read_text()
        )
        try:
            validate_public_url("http://127.0.0.1/private")
        except SafeFetchError:
            print("OK unsafe URL rejected before network access")
        else:
            raise AssertionError("unsafe URL was accepted")
    except Exception as exc:
        print(f"FAIL preflight: {type(exc).__name__}: {exc}")
        return 1
    mode = "offline" if offline else "environment-only"
    print(f"Preflight passed ({mode}); live Gemini/uAgents/Sentry gates remain separate.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    return asyncio.run(preflight(offline=args.offline))


if __name__ == "__main__":
    raise SystemExit(main())
