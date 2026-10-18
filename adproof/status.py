from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import httpx

from adproof.infrastructure.settings import Settings
from agents.common import PORTS


async def _health_report() -> dict[str, Any]:
    settings = Settings.from_env()
    addresses_path = settings.runtime_dir / "agents.json"
    addresses = (
        json.loads(addresses_path.read_text(encoding="utf-8")) if addresses_path.exists() else {}
    )
    health: dict[str, dict[str, str]] = {}
    async with httpx.AsyncClient(timeout=2.0, trust_env=False) as client:
        for role, default_port in PORTS.items():
            port = int(os.getenv(f"{role.upper()}_PORT", default_port))
            try:
                response = await client.get(f"http://127.0.0.1:{port}/health")
                response.raise_for_status()
                health[role] = {"status": "HEALTHY"}
            except (httpx.HTTPError, OSError):
                health[role] = {"status": "UNAVAILABLE"}
    return {
        "health": health,
        "public_addresses": {role: addresses.get(role, "not available") for role in PORTS},
        "runtime_dir": str(Path(settings.runtime_dir)),
    }


def main() -> int:
    report = asyncio.run(_health_report())
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if all(item["status"] == "HEALTHY" for item in report["health"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
