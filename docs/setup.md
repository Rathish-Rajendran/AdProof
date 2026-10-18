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
uv run python -m adproof.generate "Generate a Google Ads ad for AeroBeat AB-01 headphones for US adults" --offline
```

The offline suite requires no keys. MOCK is an explicit deterministic demonstration only. LIVE defaults to `gemini:gemini-3.5-flash` for all jobs and requires a billed `GEMINI_API_KEY`. Ollama with the Qwen 3B pair is an optional local alternative; install it from the [official guide](https://ollama.com/download) and pull both models if needed:

```sh
ollama pull qwen2.5:3b
ollama pull qwen2.5vl:3b
```

Model specs use `<provider>:<model>` and split at the first colon. `ADPROOF_MODEL_DEFAULT` and `ADPROOF_MODEL_IMAGE_INSPECTION` default to `gemini:gemini-3.5-flash`; claim extraction, evidence assessment, and copy remediation inherit the default unless overridden.

| Job | Environment variable | Default | Rationale |
|---|---|---|---|
| Image inspection | `ADPROOF_MODEL_IMAGE_INSPECTION` | `gemini:gemini-3.5-flash` | The only job that reads pixels, so it uses a vision-capable model. |
| Claim extraction | `ADPROOF_MODEL_CLAIM_EXTRACTION` | `gemini:gemini-3.5-flash` via the default | Text-only claim extraction. |
| Evidence assessment | `ADPROOF_MODEL_EVIDENCE_ASSESSMENT` | `gemini:gemini-3.5-flash` via the default | Text-only evidence and quote checking. |
| Copy remediation | `ADPROOF_MODEL_COPY_REMEDIATION` | `gemini:gemini-3.5-flash` via the default | Shares the text model; code validates numbers. |
| Ad generation | `ADPROOF_MODEL_AD_GENERATION` | `gemini:gemini-3.5-flash` via the default | Uses retrieved company-corpus chunks to ground generated copy. |

For optional local Qwen 3B, set `ADPROOF_MODEL_DEFAULT=ollama:qwen2.5:3b` and `ADPROOF_MODEL_IMAGE_INSPECTION=ollama:qwen2.5vl:3b`; the 3B local runs mostly ended in `HUMAN_REVIEW`. The 7B pair (`qwen2.5:7b` and `qwen2.5vl:7b`) is a higher-capacity local option, slower on CPU, and its partial results did not establish a quality improvement. The vision model is reserved for the job that reads pixels; repair shares the text model because code validates numbers. Gemini's configured model `gemini-3.5-flash` has been served as `gemini-3.6-flash` in live calls.

```sh
ollama pull qwen2.5:7b
ollama pull qwen2.5vl:7b
```

To put only evidence assessment on another provider, set `ADPROOF_MODEL_EVIDENCE_ASSESSMENT` to its `<provider>:<model>` spec and restart the agents. Gemini credentials are required when a Gemini-routed job is called. Small local models may be less accurate than Gemini and slower on CPU. On the user's 8-core, 31 GB CPU-only host, `qwen2.5vl:3b` read the only-$49 image in 42 seconds including model load and split unsafe copy into four atomic claims in 10 seconds; `gemma3:4b` took 71 seconds and 46 seconds. These are single-machine probes, not benchmarks.

## Four-agent local runtime

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

The script prepares identities on first start. The verifier, remediator, orchestrator, and generator use loopback ports 8101, 8102, 8100, and 8103. Stable private seeds are written under ignored `runtime/`; public addresses are written separately to `runtime/agents.json`. Do not delete or rotate the seeds when restarting a deployed identity. The supervisor waits for health checks and stops child processes on Ctrl-C. In another shell with `.env` exported, `uv run python -m adproof.status` reports all four health states and addresses.

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
docker compose config -q
docker compose up --build -d
docker compose ps
docker compose logs orchestrator
```

Plain Compose uses Gemini and requires `GEMINI_API_KEY` in `.env`. For local Qwen, set both Ollama model specs in `.env`, start the profile, and pull the models into its named volume:

```sh
docker compose --profile ollama up --build -d
docker compose --profile ollama exec ollama ollama pull qwen2.5:3b
docker compose --profile ollama exec ollama ollama pull qwen2.5vl:3b
```

The optional Ollama profile includes a persistent model volume. Compose shares the private named `runtime` volume and checks agent health, including the generator on port 8103. To stop the services, use `docker compose down`; do not remove volumes if the models or deployed identities must remain stable. Do not overwrite an already configured `.env`; never commit it.

## Schema and policy maintenance

`uv run python scripts/export_schemas.py` regenerates contract schemas and examples. `uv run python scripts/refresh_policy_sources.py` fetches current ACTIVE source pages through safe HTTP and reports whether each reviewed excerpt still occurs; it never updates catalog contents automatically.
