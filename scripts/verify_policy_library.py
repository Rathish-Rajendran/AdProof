from __future__ import annotations

import asyncio
import json
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from adproof.infrastructure.safe_http import validate_public_url
from adproof.infrastructure.snapshot import normalize_source

ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "data/policies/library"
ALLOWED_HOSTS = {
    "support.google.com",
    "transparency.meta.com",
    "www.ecfr.gov",
    "www.asa.org.uk",
}


async def verify() -> int:
    entries = [
        entry
        for path in sorted(LIBRARY.glob("*.json"))
        for entry in json.loads(path.read_text(encoding="utf-8"))
    ]
    sources = {entry["source_url"] for entry in entries}
    failures = 0
    async with httpx.AsyncClient(timeout=20, trust_env=False, follow_redirects=True) as client:
        snapshots = {}
        for url in sorted(sources):
            host = (urlsplit(url).hostname or "").lower()
            if host not in ALLOWED_HOSTS:
                print(f"FAIL {url}: host is not in the official-source allowlist")
                failures += 1
                continue
            try:
                validate_public_url(url)
                response = await client.get(url)
                response.raise_for_status()
                final_url = str(response.url)
                validate_public_url(final_url)
                if (urlsplit(final_url).hostname or "").lower() not in ALLOWED_HOSTS:
                    raise ValueError("redirect left the official-source allowlist")
                snapshot = normalize_source(
                    response.content,
                    url=final_url,
                    content_type=response.headers.get("content-type", ""),
                )
                snapshots[url] = snapshot
            except Exception as exc:
                print(f"FAIL {url}: {type(exc).__name__}")
                failures += 1

    for entry in entries:
        policy_id = entry["policy_id"]
        snapshot = snapshots.get(entry["source_url"])
        if snapshot is None:
            continue
        if snapshot.content_sha256 != entry["content_sha256"]:
            print(
                f"SHA_CHANGED {policy_id}: {entry['content_sha256']} -> {snapshot.content_sha256}"
            )
        for excerpt in entry["excerpts"]:
            if excerpt and excerpt in snapshot.text:
                print(f"FOUND {policy_id}: {excerpt[:90]}")
            else:
                print(f"MISSING {policy_id}: {excerpt[:90]}")
                failures += 1
        if not entry["excerpts"]:
            print(f"NO_VERIFIED_EXCERPTS {policy_id}: reference only")
    return failures


def main() -> int:
    return asyncio.run(verify())


if __name__ == "__main__":
    raise SystemExit(main())
