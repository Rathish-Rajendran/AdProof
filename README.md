# AdProof

## 1. What AdProof does

AdProof is a bounded, evidence-backed advertising preflight prototype. It extracts objective claims from one ad image and its copy, compares them with a supplied product page and bounded evidence, and identifies unsupported or contradictory claims. It may propose at most one minimal copy-only repair and independently audit the revision against the unchanged image. It never edits images or publishes ads.

```mermaid
flowchart LR
    A[ASI:One] --> B[Agentverse mailbox]
    B --> C[Orchestrator]
    C --> D[Verifier]
    C --> E[Remediator]
    D --> F["Gemini (default) / Ollama (optional)"]
    E --> F
    C -. traces and logs .-> G[Sentry]
    D -. traces and logs .-> G
    E -. traces and logs .-> G
```

See the [architecture overview](docs/architecture.md) for component details.

## 2. Prerequisites

- Python 3.11, [uv](https://docs.astral.sh/uv/), and Git.
- Install uv with the official installer:

  ```sh
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```

- A Gemini API key with billing enabled. The free tier ran out after about 6–8 calls in prior testing; one `demo aerobeat` run uses about 8. Quotas and provider behavior can change.
- Optional: Ollama installed and serving locally for local model calls. See the [official install guide](https://ollama.com/download). Pull the Qwen 3B pair if they are not already available:

  ```sh
  curl -fsSL https://ollama.com/install.sh | sh
  ollama pull qwen2.5:3b
  ollama pull qwen2.5vl:3b
  ```

- Optional Sentry DSN for tracing and logs.
- An Agentverse account and an ASI:One account, both available through [asi1.ai](https://asi1.ai). The Agentverse inspector is also available at [agentverse.ai](https://agentverse.ai).

## 3. Install and offline check

```sh
git clone https://github.com/Rathish-Rajendran/AdProof.git
cd AdProof
uv sync --frozen
uv run pytest -q
uv run ruff check .
uv run python -m adproof.demo --mode mock
```

The explicit `--mode mock` demonstration is deterministic and offline. It does not call Gemini or establish live-model performance.

## 4. Configure

If you do not already have a private environment file, create it from the example and edit it locally:

```sh
if [ ! -f .env ]; then cp .env.example .env; fi
$EDITOR .env
```

The default model spec is `ADPROOF_MODEL_DEFAULT=gemini:gemini-3.5-flash`; all jobs, including image inspection, default to Gemini. Specs use `<provider>:<model>` and split at the first colon, so Ollama tags such as `qwen2.5:3b` work.

| Job | Environment variable | Default | Rationale |
|---|---|---|---|
| Image inspection | `ADPROOF_MODEL_IMAGE_INSPECTION` | `gemini:gemini-3.5-flash` | The only job that reads image pixels, so it uses a vision-capable model. |
| Claim extraction | `ADPROOF_MODEL_CLAIM_EXTRACTION` | `gemini:gemini-3.5-flash` via the default | Text-only claim extraction. |
| Evidence assessment | `ADPROOF_MODEL_EVIDENCE_ASSESSMENT` | `gemini:gemini-3.5-flash` via the default | Text-only evidence and quote checking. |
| Copy remediation | `ADPROOF_MODEL_COPY_REMEDIATION` | `gemini:gemini-3.5-flash` via the default | Shares the text model; application code validates numeric changes. |

Ollama with `qwen2.5:3b` for text and `qwen2.5vl:3b` for image inspection is an optional local alternative. To use it, set both `ADPROOF_MODEL_DEFAULT=ollama:qwen2.5:3b` and `ADPROOF_MODEL_IMAGE_INSPECTION=ollama:qwen2.5vl:3b`; the 3B local runs mostly ended in `HUMAN_REVIEW`. The 7B pair is a higher-capacity local option but slower on CPU, and its partial run did not establish a quality improvement. The vision model is reserved for the job that reads pixels; repair shares the text model because code validates numbers. Pull either pair from the Ollama host before use:

```sh
ollama pull qwen2.5:3b
ollama pull qwen2.5vl:3b
# Optional higher-capacity local pair:
ollama pull qwen2.5:7b
ollama pull qwen2.5vl:7b
```

Set any one variable to a Gemini spec, for example `ADPROOF_MODEL_EVIDENCE_ASSESSMENT=gemini:gemini-3.5-flash`, and provide `GEMINI_API_KEY`. To switch all jobs to Gemini, set `ADPROOF_MODEL_DEFAULT=gemini:gemini-3.5-flash` and `ADPROOF_MODEL_IMAGE_INSPECTION=gemini:gemini-3.5-flash` and provide the key. Restart the agents after changing `.env`. Gemini credentials are required only when a Gemini-routed job is called. `OLLAMA_BASE_URL` defaults to `http://127.0.0.1:11434`, and the workflow deadline defaults to 600 seconds. Set `ADPROOF_MAILBOX_ENABLED=1` for Agentverse/ASI:One. Optionally set `SENTRY_DSN`, `SENTRY_ENVIRONMENT`, and `SENTRY_TRACES_SAMPLE_RATE=1.0`. Do not paste keys or seed values into source files, logs, issues, or commits.

The local Python settings and `scripts/run_all.sh` do **not** load `.env` automatically. Export its values in each shell before starting local commands, and keep that shell open:

```sh
set -a
source .env
set +a
```

On first start, the runtime generates private identities in `runtime/agent-seeds.json` and writes their public addresses to `runtime/agents.json`. The seed file is gitignored and mode `0600`; back it up securely to preserve the agent addresses and mailbox identity. You may supply `ORCHESTRATOR_SEED`, `VERIFIER_SEED`, and `REMEDIATOR_SEED` in `.env` instead. Never publish those values.

## 5. Live model evaluation

With the environment loaded as above and `GEMINI_API_KEY` configured, evaluate the default Gemini provider:

```sh
uv run python -m adproof.eval --live --cases 1,2 --max-model-calls 12
```

This makes live model calls and writes a JSON report under `runtime/eval/`. Case 1 is expected to find unsafe claims and decide `FIX_REQUIRED`; case 2 is expected to pass. Gemini calls may incur charges and provider quotas can produce `HUMAN_REVIEW`; successful calls for the configured `gemini-3.5-flash` have reported served model `gemini-3.6-flash`.

On an 8-core, 31 GB CPU-only machine, the user measured the `qwen2.5vl:3b` probe reading the only-$49 image correctly in 42 seconds including model load and splitting the unsafe copy into four atomic claims in 10 seconds. `gemma3:4b` also produced the correct outputs but took 71 seconds and 46 seconds, respectively. These are single-machine observations, not benchmarks for the current per-job mapping. Small local models may be less accurate than Gemini and can be slow on CPU; review each live result rather than treating model output as guaranteed.

An earlier single-model four-case live run on 2026-10-18 did not meet expected quality: cases 1, 2, and 4 returned `HUMAN_REVIEW`, and case 3 did not identify the `$49` image issue. The current per-job case-1 result also returned `HUMAN_REVIEW` rather than `FIX_REQUIRED`. Treat local models as experimental; the detailed results and artifacts are in the [validation status](docs/validation-status.md).

## 6. Start the three agents

In the same shell where `.env` is exported:

```sh
bash scripts/run_all.sh
```

The script prepares the runtime, starts the orchestrator, verifier, and remediator, and stays in the foreground. It prints `All local agents are healthy. Press Ctrl-C to stop them.` after the `/health` checks pass. Logs are `runtime/orchestrator.log`, `runtime/verifier.log`, and `runtime/remediator.log`; the orchestrator log contains the Agent inspector URL.

In a second terminal, load the environment there too, then check health and public addresses:

```sh
# Run these from the repository root.
set -a
source .env
set +a
uv run python -m adproof.status
```

Healthy output lists `HEALTHY` for all three roles. Stop the foreground supervisor with Ctrl-C; it stops the child agents.

## 7. Connect the orchestrator to Agentverse (mailbox)

1. Find the inspector URL in `runtime/orchestrator.log` (for example, search for `Agent inspector available at`) and copy it without exposing secrets.
2. Open that URL in a browser **on the same machine running the agent**. The inspector connects to `http://127.0.0.1:8100`; a browser on another computer checks that computer's loopback and will not find this agent.
3. Sign in to Agentverse (bottom-left), select **Connect → Mailbox**, and accept the **Check your agent** dialog. Start the orchestrator with `ADPROOF_MAILBOX_ENABLED=1` first; `mailbox=True` is already configured, so this Connect step requires no code change or restart.
4. Success indicators: `runtime/orchestrator.log` shows `[mailbox]: Successfully registered as mailbox agent in Agentverse`, the inspector shows **Modify connection / Agent Profile**, and the orchestrator appears under **Agentverse → My Agents**.
5. Optionally confirm the public Almanac API record:

   ```sh
   ORCHESTRATOR_ADDRESS="$(uv run python -c 'import json; print(json.load(open("runtime/agents.json"))["orchestrator"])')"
   curl -fsS "https://agentverse.ai/v1/almanac/agents/${ORCHESTRATOR_ADDRESS}"
   ```

   A connected mailbox reports `status: active` and `type: mailbox`.
6. The “not enough funds to register on Almanac contract” warning is harmless. Successful Almanac API mailbox registration is sufficient; on-chain contract registration is optional and requires no funds for this workflow.
7. Optionally set `ADPROOF_ORCHESTRATOR_HANDLE` to a unique Agentverse handle. Re-run the inspector's **Modify connection / Connect** flow after setting or changing it. ASI:One `@handle` support is unverified; use the full agent address.

## 8. Test in ASI:One

1. At [asi1.ai](https://asi1.ai), start a chat and put `adproof-orchestrator` in the **To:** box, or prefix each message with `@<orchestrator address>`. Without the `@` mention or recipient, the message goes to ASI:One's own AI.
2. Send `help`, then `demo aerobeat`.
3. The expected case-1 result is an original `FIX_REQUIRED` audit with four issues: two `AD_LANDING_PAGE_CONTRADICTION` findings for waterproof and 48-hour battery claims, `UNVERIFIED_ENDORSEMENT` for the unsupported athlete endorsement, and `PRICE_DISCOUNT_MISMATCH` for the 50%-off claim (the evidence establishes 25%). The workflow proposes one copy-only repair and independently re-checks it against the same image. The latest user-reported live run passed all steps in about 19.4 seconds. ASI:One now returns one pretty-printed JSON block rather than a result card; for example:

   ```json
   {
     "audit_id": "8fef0a98d3ad4144a805427ce679228a",
     "original_check": {
       "decision": "FIX_REQUIRED",
       "issues": [
         {"claim": "AeroBeat headphones are completely waterproof.", "status": "CONTRADICTED", "why": "The source says the headphones are not waterproof."},
         {"claim": "Get 48-hour battery life with noise cancellation off.", "status": "CONTRADICTED", "why": "The source gives up to 30 hours."},
         {"claim": "Recommended by 1,000 athletes.", "status": "INSUFFICIENT_EVIDENCE", "why": "The source contains no endorsement information."},
         {"claim": "AeroBeat headphones are 50% off.", "status": "CONTRADICTED", "why": "The supplied prices establish 25% off."}
       ]
     },
     "fix": {
       "ad_copy": "AeroBeat headphones are splash-resistant for everyday use. Get up to 30 hours of battery life with noise cancellation off. Now $60—25% off!"
     },
     "recheck": {"decision": "PASS", "issues": [], "changed_decision": true},
     "final": {
       "decision": "PASS",
       "ad_copy": "AeroBeat headphones are splash-resistant for everyday use. Get up to 30 hours of battery life with noise cancellation off. Now $60—25% off!",
       "repair_verified": true
     }
   }
   ```

   The `report <audit_id>` and `status <audit_id>` text commands still work.
4. Try `demo aerobeat49` to see that a copy edit cannot change the `$49` shown in the image, so the image issue remains `FIX_REQUIRED`; `demo aerobeat correct` audits the already-correct ad.
5. `HUMAN_REVIEW` with `MODEL_UNAVAILABLE` generally indicates quota exhaustion (often HTTP 429) or provider unavailability (often HTTP 503). `MODEL_AUTH` (HTTP 401) indicates a bad or stale key: update `.env`, re-export it, and restart the agents so they use the new value.

## 9. Always-on hosting (Docker)

Use the private `.env` from section 4; if starting from a fresh checkout, create it from the example and fill `GEMINI_API_KEY`. Plain Compose uses Gemini by default. Set `ADPROOF_MAILBOX_ENABLED=1`:

```sh
if [ ! -f .env ]; then cp .env.example .env; fi
$EDITOR .env
docker compose config --quiet
docker compose up --build -d
docker compose ps
docker compose logs orchestrator
```

For the optional local Qwen service, uncomment the two Ollama model specs in `.env`, then enable the profile:

```sh
docker compose --profile ollama up --build -d ollama
docker compose --profile ollama exec ollama ollama pull qwen2.5:3b
docker compose --profile ollama exec ollama ollama pull qwen2.5vl:3b
docker compose --profile ollama up --build -d
```

Compose loads `.env` itself. The named `ollama_models` volume retains downloaded local models; the named `runtime` volume holds container identities across restarts. To retain the address already connected in Agentverse, privately copy the values from your existing `runtime/agent-seeds.json` into `ORCHESTRATOR_SEED`, `VERIFIER_SEED`, and `REMEDIATOR_SEED` in `.env`; never print or commit them. Connect the mailbox using a browser on the Docker host, where port 8100 is published. Restart the Compose services after changing model settings.

**Docker validation:** Docker is available in the validation environment; both `docker compose config -q` and `docker compose --profile ollama config -q` were validated using a temporary `.env` copied from `.env.example`. The full `docker compose up` was **not** tested in this validation.

## 10. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| “Agent mailbox not found” | The orchestrator mailbox has not been connected yet. | Follow [step 7](#7-connect-the-orchestrator-to-agentverse-mailbox). |
| Inspector **Connect** is greyed out | Not signed in, or the inspector was opened in a browser on another machine. | Sign in and open the inspector on the machine running the agent. |
| Agentverse **My Agents** is empty | The inspector Connect flow was not completed. | Complete [step 7](#7-connect-the-orchestrator-to-agentverse-mailbox). |
| ASI:One does not reply | Agents are stopped, the host is asleep, or the message was not addressed to the agent. | Check `runtime/orchestrator.log`, verify the recipient/`@` mention, and restart the agents if needed. |
| `Request could not be processed (ValueError)` | An old build does not strip ASI:One's leading `@` mention. | Pull/update the current code and restart the orchestrator. |
| `MODEL_AUTH` HTTP 401 | The configured key is invalid or stale. | Update `.env`, re-export it, and restart/recreate the agents. |
| `MODEL_UNAVAILABLE` / model not found | Gemini quota/provider errors, or an unavailable/unpulled optional Ollama model. | Enable Gemini billing or retry after provider outages; if using local Ollama, start its profile and pull the selected model. |
| “Not enough funds to register on Almanac contract” | Optional on-chain registration was skipped. | No action needed; successful Almanac API mailbox registration is sufficient. |

## 11. Validation status

See the detailed [validation status](docs/validation-status.md). Live Agentverse mailbox registration, Sentry ingestion, and ASI:One help have passed. The user reports that the latest Gemini ASI:One run completed the original four-issue `FIX_REQUIRED` audit, one copy-only repair, independent `PASS` re-check, and final `PASS` with `repair_verified=true` in about 19.4 seconds. Earlier 3B local runs mostly ended in `HUMAN_REVIEW`; the interrupted 7B run did not establish a quality improvement.

## 12. Agent addresses

These current public addresses are derived from the private seeds in `runtime/agent-seeds.json` and listed in `runtime/agents.json`. They change if the seeds are rotated.

| Agent | Current public address |
|---|---|
| Orchestrator | `agent1q0lpgrz6c80h2n5ns0vw5sq0wtrp8gkm92x3pl6n5hwru7z0f47977ntemy` |
| Verifier | `agent1qv78z88d9lj2cmgf5yjg853ulc0sw8v4qmscar56wr8rqsn97xk9c08deh8` |
| Remediator | `agent1qfc0a6u3lq3azyj93ptz3lkx6rkvhgggg5n7knx6g45fncl4f5qqqfwenq8` |

## Scope and limitations

**Scope:** Google Ads, United States, English, adult-targeted general consumer electronics. A PASS means only that the checks and sources named in that report completed; it is not legal advice, legal review, platform certification, approval, or a safety guarantee. The service does not publish ads.

One campaign supports one PNG/JPEG image, one copy string, one HTTPS landing page, and up to three supplied text/HTML evidence documents. Authenticated pages, PDFs, arbitrary browsing, other locales/platforms/categories, and campaign publishing are out of scope. Unavailable evidence, unsupported context, and materially unreadable image text require review. See [policy scope](docs/policy-scope.md), [architecture](docs/architecture.md), [evaluation](docs/evaluation.md), [setup](docs/setup.md), and the [build brief](docs/build-brief/DEVIN_MASTER_PROMPT.md).

## MOCK vs LIVE

- `MOCK` is selected explicitly with `uv run python -m adproof.demo --mode mock`; it uses deterministic fixtures and is offline.
- `LIVE` uses the configured provider (Gemini by default; Ollama is optional) and real supplied HTTPS sources. Errors remain typed errors; there is no silent fallback to fixture outputs.
- A job spec such as `gemini:gemini-3.5-flash` opts that job into Gemini; only Gemini-routed jobs require `GEMINI_API_KEY` and can incur provider charges. Keep credentials in the environment or a secret manager, never in source control.
- The bounded live evaluator writes its JSON report under `runtime/eval/`; see [evaluation](docs/evaluation.md).
