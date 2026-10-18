# Setup and operations

For the complete reproducible workflow—including Agentverse mailbox connection, ASI:One testing, Docker hosting, current addresses, and live validation—see the numbered [README guide](../README.md).

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

The offline suite requires no keys. MOCK is an explicit deterministic demonstration only. LIVE defaults to local Ollama at `http://127.0.0.1:11434`, with `qwen2.5vl:3b` for image inspection and `qwen2.5:3b` for text jobs. Install Ollama from the [official guide](https://ollama.com/download), then pull both models if they are not already present:

```sh
ollama pull qwen2.5:3b
ollama pull qwen2.5vl:3b
```

Model specs use `<provider>:<model>` and split at the first colon. `ADPROOF_MODEL_DEFAULT` defaults to `ollama:qwen2.5:3b`; `ADPROOF_MODEL_IMAGE_INSPECTION` defaults to `ollama:qwen2.5vl:3b`; claim extraction, evidence assessment, and copy remediation inherit the default unless overridden.

| Job | Environment variable | Default | Rationale |
|---|---|---|---|
| Image inspection | `ADPROOF_MODEL_IMAGE_INSPECTION` | `ollama:qwen2.5vl:3b` | The only job that reads pixels, so it uses a vision model. |
| Claim extraction | `ADPROOF_MODEL_CLAIM_EXTRACTION` | `ollama:qwen2.5:3b` via the default | Text-only 3B for instruction following and JSON with lower CPU latency. |
| Evidence assessment | `ADPROOF_MODEL_EVIDENCE_ASSESSMENT` | `ollama:qwen2.5:3b` via the default | Text-only evidence and quote checking. |
| Copy remediation | `ADPROOF_MODEL_COPY_REMEDIATION` | `ollama:qwen2.5:3b` via the default | Shares the text model; code validates numbers. |

The 7B pair (`qwen2.5:7b` and `qwen2.5vl:7b`) is the higher-accuracy local option, but slower on CPU; the partial 7B results below did not establish a quality improvement. The text model is intended to provide stronger instruction following and structured JSON, while the vision model is reserved for the job that reads pixels; repair shares the text model because code validates numbers. Pull both and set `ADPROOF_MODEL_DEFAULT=ollama:qwen2.5:7b` and `ADPROOF_MODEL_IMAGE_INSPECTION=ollama:qwen2.5vl:7b`:

```sh
ollama pull qwen2.5:7b
ollama pull qwen2.5vl:7b
```

To put only evidence assessment on Gemini, set `ADPROOF_MODEL_EVIDENCE_ASSESSMENT=gemini:gemini-3.5-flash` and configure `GEMINI_API_KEY`; restart the agents. To switch all jobs to Gemini, set `ADPROOF_MODEL_DEFAULT=gemini:gemini-3.5-flash` and `ADPROOF_MODEL_IMAGE_INSPECTION=gemini:gemini-3.5-flash`, configure the key, and restart the agents. Gemini credentials are required only when a Gemini-routed job is called. The workflow deadline defaults to 600 seconds to accommodate local CPU inference. Small local models may be less accurate than Gemini and slower on CPU. On the user's 8-core, 31 GB CPU-only host, `qwen2.5vl:3b` read the only-$49 image in 42 seconds including model load and split unsafe copy into four atomic claims in 10 seconds; `gemma3:4b` took 71 seconds and 46 seconds. These are single-machine probes, not benchmarks.

## Three-agent local runtime

The Python settings and `scripts/run_all.sh` do not load `.env` automatically. Create it from `.env.example` if needed, edit it privately, then export its values in every shell used to run the agents or status command:

```sh
set -a
source .env
set +a
```

From the repository root, start all agents under the supervisor:

```sh
bash scripts/run_all.sh
```

The script prepares identities on first start. The verifier, remediator, and orchestrator use loopback ports 8101, 8102, and 8100. Stable private seeds are written under ignored `runtime/`; public addresses are written separately to `runtime/agents.json`. Do not delete or rotate the seeds when restarting a deployed identity. The supervisor waits for health checks and stops child processes on Ctrl-C. In another shell with `.env` exported, `uv run python -m adproof.status` reports all three health states and addresses.

The transport proof command runs a test ACP client and verifies delayed replies and watchdog timeouts against the original chat session:

```sh
bash scripts/run_transport_proof.sh
```

The mailbox switch is disabled by default. For Agentverse/ASI:One, set `ADPROOF_MAILBOX_ENABLED=1` and keep the orchestrator running on a reachable host. Specialists retain explicit local HTTP endpoints and a resolver map. The mailbox-mode local reachability proof passed. Connect the orchestrator mailbox through **Inspector → Connect → Mailbox**; successful Almanac API registration is sufficient, and on-chain contract registration is not required. See `docs/validation-status.md`.

Optionally set `ADPROOF_ORCHESTRATOR_HANDLE` to publish a human-readable handle for the public orchestrator. Handles must be unique on Agentverse. After setting or changing it, re-run the Agentverse inspector's **Modify connection** / **Connect** flow for the orchestrator mailbox. ASI:One `@handle` support is unverified; use the full agent address unless tested.

## Docker Compose

For the complete mailbox-enabled, always-on setup and current Docker validation status, follow [README section 9](../README.md#9-always-on-hosting-docker). Compose reads `.env` directly; the local-shell export step above does not apply to Compose.

```sh
if [ ! -f .env ]; then cp .env.example .env; fi
docker compose config --quiet
docker compose up --build -d ollama
docker compose exec ollama ollama pull qwen2.5:3b
docker compose exec ollama ollama pull qwen2.5vl:3b
# Optional higher-accuracy local pair:
docker compose exec ollama ollama pull qwen2.5:7b
docker compose exec ollama ollama pull qwen2.5vl:7b
docker compose up --build -d
docker compose ps
docker compose logs orchestrator
```

Compose runs Ollama plus the three agents, stores downloaded models in the named `ollama_models` volume, shares the private named `runtime` volume, and checks agent health. No Gemini key is required for the default local models. To route a job through Gemini, set its `ADPROOF_MODEL_*` variable to a `gemini:<model>` spec and provide `GEMINI_API_KEY` in `.env`, then restart the services. To stop them, use `docker compose down`; do not remove volumes if the models or deployed agent identities must remain stable. Do not overwrite an already configured `.env`; never commit it.

## Schema and policy maintenance

`uv run python scripts/export_schemas.py` regenerates contract schemas and examples. `uv run python scripts/refresh_policy_sources.py` fetches current ACTIVE source pages through safe HTTP and reports whether each reviewed excerpt still occurs; it never updates catalog contents automatically.
