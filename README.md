# AdProof

AdProof is a bounded evidence-backed preflight and copy-repair prototype for AI-generated advertising. It compares objective ad claims with supplied product-page evidence, identifies inconsistencies, and can propose one copy-only repair for independent re-audit.

The supported demonstration scope is Google Ads, United States, English, explicitly adult-targeted general consumer electronics. It does not publish ads, provide legal advice, guarantee safety, or certify platform approval. A PASS applies only to the checks and sources named in that audit.

## Development

Requires Python 3.11 and [uv](https://docs.astral.sh/uv/):

```sh
uv sync --frozen
uv run pytest -q
uv run ruff check .
uv run python -m adproof.preflight --offline
uv run python -m adproof.demo --mode mock
```

For live inference, set `GEMINI_API_KEY` privately and optionally configure `GEMINI_MODEL`; live calls are paid and never fall back to fixtures. The three uAgents workers and their addresses/seeds are documented under `agents/`.

The real-agent services use local loopback endpoints and persistent per-role seeds in the ignored `runtime/` directory. Run `bash scripts/run_all.sh` to prepare identities, wait for health endpoints, and stop all child agents on Ctrl-C. The private `ADPROOF_MAILBOX_ENABLED` switch is off by default. `bash scripts/run_transport_proof.sh` enables a test-only delayed-reply/watchdog probe and compares both response session UUIDs with the original chat session.

Refresh reviewed policy citations with `uv run python scripts/refresh_policy_sources.py`; the command reports source drift and never edits the reviewed catalog. `uv run python scripts/export_schemas.py` regenerates strict domain schemas and examples. For opt-in live Gemini image/JSON checks (paid inference, model is `gemini-3.8-flash` by default), run `uv run python -m adproof.live_smoke --max-model-calls 20`.

## Limits

The prototype supports one PNG/JPEG image, one copy string, one supplied HTTPS landing page, and up to three supplied text/HTML evidence documents. PDFs, authenticated pages, arbitrary browsing, other locales/platforms/categories, and automated campaign publishing are out of scope. Unavailable evidence, unsupported context, and materially unreadable image text require review.

See [policy scope](docs/policy-scope.md), [setup](docs/setup.md), and the [build brief](docs/build-brief/DEVIN_MASTER_PROMPT.md).
