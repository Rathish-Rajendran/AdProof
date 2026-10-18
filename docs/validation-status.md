# Validation status

Only executed checks may be marked PASS. This file is updated with exact commands and results during validation.

| Gate | Status | Evidence |
|---|---|---|
| Offline install, tests, lint, schemas | PASS | `uv sync --frozen` succeeded; latest `uv run pytest -q` — 97 passed (includes schema staleness); `uv run ruff check .` — all checks passed; `uv run ruff format --check .` — 81 files already formatted. |
| Offline preflight and MOCK compatibility | PASS | Latest `uv run python -m adproof.preflight --offline` passed. Latest explicit MOCK demo reported `FIX_REQUIRED` for the unsafe case-1 copy with synthetic claims and arithmetic; it is not live model evidence. Legacy MOCK suite/server were validated before these changes. |
| Secret-safe artifacts and runtime state | PARTIAL | `.env.example` contains names only; runtime seed/address/database paths are gitignored. No dedicated secret-scanner run was performed. |
| Contracts, decisions, evidence, arithmetic, safety, store, and repair tests | PARTIAL | Offline unit tests cover strict contracts, all report-selection branches, quote validation, price arithmetic, policy provenance, SSRF/image checks, store behavior, and remediator validation; not every §9 scenario is implemented. |
| Live evaluation cases 1–4 | BLOCKED | Current run `runtime/eval/3a8592f860444d168b3eb8591f8ab153.json`, model `gemini-3.8-flash`, shared cap 40. One model call per case (4 total); each returned HTTP 429 `RESOURCE_EXHAUSTED` / `MODEL_UNAVAILABLE`, `retryable=false`, quota exhausted. All actual decisions were `HUMAN_REVIEW`; expected were case 1 `FIX_REQUIRED`, 2 `PASS`, 3 `FIX_REQUIRED`, 4 `PASS`. No claim statuses or arithmetic were available; evidence-ID validity is vacuously true with no claims. No model substitution or fixture fallback. |
| Three local agents and correlated specialist transport | PASS | Three local agent processes used explicit loopback endpoints and the `RulesBasedResolver`; verifier fetched the pinned public source. Local health/status and message correlation were exercised. |
| Official ACP cards and reply order | PASS | Result card uses the installed chat cards protocol `DetailCardPayload` and official create/validate/extract helpers; tests cover create → validate → response → extract, action authorization/idempotency, and plain text → card → terminal ordering. |
| Delayed reply and watchdog preserve original ACP session | PASS | Mailbox-enabled run (`ADPROOF_MAILBOX_ENABLED=1`) proved delayed specialist and watchdog `TASK_TIMEOUT` replies reached session `9e81490b-bb9f-4945-93ec-5afdf004f80f`. `runtime/orchestrator.log` confirms mailbox client startup and no `Endpoint configuration overrides mailbox setting` warning; local proof passed. Agentverse reported mailbox not found until created via inspector; contract registration also needs funds. |
| Three-agent verify → repair → reverify against live Gemini | BLOCKED | Current mailbox-enabled `demo aerobeat` run returned `HUMAN_REVIEW`; Gemini quota HTTP 429 occurred during image inspection, so no repair or re-verification was reached. Client session `02cdcef6-ec4d-41d9-b36e-8b48f8aa2b51`; result was captured by the local ACP client. |
| Agentverse registration and ASI:One discoverability | PARTIAL | Local SDK startup emitted inspector URLs and Almanac API registration success. Contract registration warned that the agents lack funds; no public deployment or ASI:One registration was performed. |
| Full primary ASI:One workflow | PENDING | Requires the intended public runtime/account action. |
| Sentry trace/log ingestion | PARTIAL | `SENTRY_ENVIRONMENT=devin-dev`; traceparents emitted: `64dbe042f73e44fcb74fd2ecb377fd73-8a8c2d0975399b0c-1` (live-smoke case 1) and `3dfb854a77e9433a94314c9c598d6376-b0c73e1b57ea65b9-1` (three-agent workflow). SDK reported pending events; ingestion was not independently confirmed in the Sentry account. |
| Intended judging runtime remains available | PENDING | Human runtime action. |
| Public README setup, scope, examples, and real agent links | PARTIAL | Setup and scope are documented; only local derived agent addresses exist in ignored `runtime/agents.json`. No public agent links are available. |
| Baseline and hackathon provenance | PASS | Master prompt, reference plans, and unchanged legacy MOCK bundle are included; legacy tests and server command passed. |
| Pull request against verified base | PENDING | Lead opens PR. |

The latest local workflow returned audit `3f92ce330eb74d84912a8b1cbf3d88eb` as `HUMAN_REVIEW`; Sentry ingestion was not independently confirmed. Runtime seeds remain only in ignored `runtime/` files and are not recorded here.
