# Setup and operations

## Local development

Install Python 3.11 and uv, then install the frozen dependency set:

```sh
uv sync --frozen
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run python -m adproof.preflight --offline
uv run python -m adproof.demo --mode mock
```

The offline suite requires no keys. MOCK is an explicit deterministic demonstration only. LIVE requires a privately configured `GEMINI_API_KEY`; `GEMINI_MODEL` selects the model and defaults to `gemini-3.5-flash`. `SENTRY_DSN` is optional and must not affect audit outcomes.

## Three-agent local runtime

Copy `.env.example` to `.env` only if you need local secrets or overrides; keep `.env` private. To start all agents under the supervisor:

```sh
uv run python scripts/prepare_runtime.py
bash scripts/run_all.sh
```

The verifier, remediator, and orchestrator use loopback ports 8101, 8102, and 8100. Stable private seeds are written under ignored `runtime/`; public addresses are written separately to `runtime/agents.json`. Do not delete or rotate the seeds when restarting a deployed identity. The supervisor waits for health checks and stops child processes on Ctrl-C. `uv run python -m adproof.status` reports all three health states and addresses.

The transport proof command runs a test ACP client and verifies delayed replies and watchdog timeouts against the original chat session:

```sh
bash scripts/run_transport_proof.sh
```

The mailbox switch is disabled by default. For Agentverse/ASI:One, set `ADPROOF_MAILBOX_ENABLED=1` and keep the orchestrator running on a reachable host. Specialists retain explicit local HTTP endpoints and a resolver map. The mailbox-mode local reachability proof passed. Connect the orchestrator mailbox through **Inspector → Connect → Mailbox**; successful Almanac API registration is sufficient, and on-chain contract registration is not required. See `docs/validation-status.md`.

Optionally set `ADPROOF_ORCHESTRATOR_HANDLE` to publish a human-readable handle for the public orchestrator. Handles must be unique on Agentverse. After setting or changing it, re-run the Agentverse inspector's **Modify connection** / **Connect** flow for the orchestrator mailbox. ASI:One `@handle` support is unverified; use the full agent address unless tested.

## Docker Compose

```sh
cp .env.example .env
# Add privately supplied model credentials to .env if LIVE inference is required.
docker compose run --rm --no-deps orchestrator python scripts/prepare_runtime.py
docker compose up --build
```

Compose runs three services, shares the private `runtime` volume, and checks `/health` on each process. It requires a usable model key because the workers are configured for LIVE processing. To stop them, use `docker compose down`; do not remove the volume if the deployed agent identities must remain stable.

## Schema and policy maintenance

`uv run python scripts/export_schemas.py` regenerates contract schemas and examples. `uv run python scripts/refresh_policy_sources.py` fetches current ACTIVE source pages through safe HTTP and reports whether each reviewed excerpt still occurs; it never updates catalog contents automatically.
