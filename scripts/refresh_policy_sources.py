from __future__ import annotations

import asyncio
import json
from pathlib import Path

from adproof.infrastructure.safe_http import SafeHttpClient
from adproof.infrastructure.snapshot import normalize_source

ROOT = Path(__file__).resolve().parents[1]


async def refresh() -> int:
    catalog = json.loads((ROOT / "data/policies/catalog.json").read_text(encoding="utf-8"))
    active = [rule for rule in catalog["rules"] if rule["review_status"] == "ACTIVE"]
    failures = 0
    client = SafeHttpClient(timeout=10)
    try:
        for rule in active:
            if (
                not rule.get("excerpt")
                or not rule.get("content_sha256")
                or not rule.get("retrieved_at")
            ):
                print(f"FAIL {rule['rule_id']}: ACTIVE rule lacks source provenance")
                failures += 1
                continue
            try:
                source = await client.fetch(rule["source_url"], max_bytes=2 * 1024 * 1024)
                snapshot = normalize_source(
                    source.content,
                    url=source.url,
                    content_type=source.headers.get("content-type", ""),
                )
            except Exception as exc:
                print(f"UNAVAILABLE {rule['rule_id']}: {type(exc).__name__}")
                failures += 1
                continue
            if rule["excerpt"] in snapshot.text:
                print(f"OK {rule['rule_id']}: excerpt still occurs in fetched normalized source")
            else:
                print(f"REVIEW {rule['rule_id']}: excerpt not found; catalog was not changed")
                failures += 1
    finally:
        await client.close()
    return int(failures > 0)


def main() -> int:
    return asyncio.run(refresh())


if __name__ == "__main__":
    raise SystemExit(main())
