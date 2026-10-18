# Validation status

Only executed checks may be marked PASS. This file is updated with exact commands and results during validation.

| Gate | Status | Evidence |
|---|---|---|
| Offline install, tests, lint, schemas | PASS | `uv sync --frozen` succeeded; latest `uv run pytest -q` — 101 passed (includes schema staleness and repair-number regression); `uv run ruff check .` — all checks passed; `uv run ruff format --check .` — 82 files already formatted. |
| Offline preflight and MOCK compatibility | PASS | Latest `uv run python -m adproof.preflight --offline` passed. Latest explicit MOCK demo reported `FIX_REQUIRED` for the unsafe case-1 copy with synthetic claims and arithmetic; it is not live model evidence. Legacy MOCK suite/server were validated before these changes. |
| Secret-safe artifacts and runtime state | PARTIAL | `.env.example` contains names only; runtime seed/address/database paths are gitignored. No dedicated secret-scanner run was performed. |
| Contracts, decisions, evidence, arithmetic, safety, store, and repair tests | PARTIAL | Offline unit tests cover strict contracts, all report-selection branches, quote validation, price arithmetic, policy provenance, SSRF/image checks, store behavior, and remediator validation; not every §9 scenario is implemented. |
| Live evaluation cases 1–4 | PARTIAL | Latest run `runtime/eval/3174cec9ee434b568b9ce547f8e9d375.json`, configured `gemini-3.5-flash`, budget 40, 8 calls used. Cases 1–2 matched expected decisions; cases 3–4 returned non-retryable quota `MODEL_UNAVAILABLE` (HTTP 429) and `HUMAN_REVIEW`. Detailed claims, arithmetic, call latencies, and artifact notes follow below. Successful call records reported `gemini-3.6-flash`; no fallback or model substitution. |
| Three local agents and correlated specialist transport | PASS | Three local agent processes used explicit loopback endpoints and the `RulesBasedResolver`; verifier fetched the pinned public source. Local health/status and message correlation were exercised. |
| Official ACP cards and reply order | PASS | Result card uses the installed chat cards protocol `DetailCardPayload` and official create/validate/extract helpers; tests cover create → validate → response → extract, action authorization/idempotency, and plain text → card → terminal ordering. |
| Delayed reply and watchdog preserve original ACP session | PASS | Mailbox-enabled run (`ADPROOF_MAILBOX_ENABLED=1`) proved delayed specialist and watchdog `TASK_TIMEOUT` replies reached session `9e81490b-bb9f-4945-93ec-5afdf004f80f`. `runtime/orchestrator.log` confirms mailbox client startup and no `Endpoint configuration overrides mailbox setting` warning; local proof passed. The orchestrator mailbox was subsequently confirmed active in Agentverse on 2026-10-18; see details below. |
| Three-agent verify → repair → reverify against live Gemini | PARTIAL | Latest user-reported case-1 run had original decision `FIX_REQUIRED`, then re-verification returned `HUMAN_REVIEW` after HTTP 429 quota exhaustion. Workflow was `PARTIAL` and the repair remained unverified. Audit `b3d4f79e1cf44d7da6bc7fe5d90e4c20`, client session `cacab77b-5206-4f44-a4a5-7108c0506f20`, served model `gemini-3.6-flash`; see the latest run details below. |
| Agentverse orchestrator mailbox | PASS | User connected the orchestrator mailbox and confirmed active Almanac API registration on 2026-10-18. The response showed `status: active`, `type: mailbox`, the mailbox submit endpoint, 2 protocols, and expiry `2026-11-16T23:01:11Z`; see details below. |
| Almanac on-chain contract registration | NOT REQUIRED | The `uagents 0.26.1` `DefaultRegistrationPolicy` registers through the Almanac API first, then swallows `InsufficientFundsError` for the contract step. The wallet was unfunded; no funds were spent or requested. |
| Full primary ASI:One workflow | PENDING | Remains pending until the user reports an ASI:One test. |
| Sentry trace/log ingestion | PASS | User confirmed ingestion in their Sentry account on 2026-10-18. Earlier traceparents were emitted for the live smoke (`64dbe042f73e44fcb74fd2ecb377fd73-8a8c2d0975399b0c-1`), three-agent workflow (`3dfb854a77e9433a94314c9c598d6376-b0c73e1b57ea65b9-1`), and mailbox demo (`66d8628ea5da4d7fb4e90934ad90aab9-b1a24a7d2180bdf1-0`). |
| Intended judging runtime remains available | PENDING | Human runtime action. |
| Public README setup, scope, examples, and real agent links | PARTIAL | Setup and scope are documented; only local derived agent addresses exist in ignored `runtime/agents.json`. No public agent links are available. |
| Baseline and hackathon provenance | PASS | Master prompt, reference plans, and unchanged legacy MOCK bundle are included; legacy tests and server command passed. |
| Pull request against verified base | PENDING | Lead opens PR. |

Runtime seeds remain only in ignored `runtime/` files and are not recorded here.

## Latest live evaluation: Gemini default approval

Run ID `3174cec9ee434b568b9ce547f8e9d375` ran on 2026-10-18 with configured model `gemini-3.5-flash` and a shared 40-call budget. It consumed 8 calls. Successful provider call records reported the served version `gemini-3.6-flash`. The top-level `reported_model_versions` field in this first artifact also contains configured fallback `gemini-3.5-flash`; the reporting helper was subsequently corrected to include only successful provider call records. The artifact is preserved as produced.

| Case | Expected → actual | Claims and arithmetic | Calls and timing |
|---|---|---|---|
| 1 | `FIX_REQUIRED` → `FIX_REQUIRED` (match) | `CONTRADICTED`: waterproof, 48-hour battery, athlete endorsement, and 50% discount; `SUPPORTED`: `$60` current price. Arithmetic: `$80` to `$60` = 25% off, versus stated 50% (0.5 percentage-point tolerance). Evidence IDs valid. | 4 successful calls: image inspection 2.182 s; claim extraction 2.393 s; evidence assessment 3.036 s; copy remediation 3.123 s. Workflow 11.054 s; wall 11.064 s. Provider-reported version `gemini-3.6-flash`. Workflow status was `PARTIAL`: the model proposed `25%` while derivation contained `25.0`; numeric string validation rejected the equivalent formatting and no revised audit was produced. This deterministic validation issue was fixed afterward using Decimal numeric tokens and covered by a regression test; no prompt change was made. |
| 2 | `PASS` → `PASS` (match) | All four extracted claims `SUPPORTED`: 25% discount, `$60` down from `$80`, splash resistance, and up to 30 hours with noise cancellation off. No arithmetic issue. Evidence IDs valid. | 2 successful calls: claim extraction 41.759 s; evidence assessment 3.316 s. Workflow 45.175 s; wall 45.191 s. Provider-reported version `gemini-3.6-flash`. |
| 3 | `FIX_REQUIRED` → `HUMAN_REVIEW` (quota-blocked) | No claims or arithmetic were available; the `$49` image issue was not assessed. Evidence-ID validity is vacuous because there are no claims. | 1 image-inspection call: HTTP 429 `RESOURCE_EXHAUSTED`, typed `MODEL_UNAVAILABLE`, quota exhausted, `retryable=false`, 0.212 s. Workflow 0.387 s; wall 0.397 s. No provider-reported version for the failed call. |
| 4 | `PASS` → `HUMAN_REVIEW` (quota-blocked) | No claims or arithmetic were available. Evidence-ID validity is vacuous because there are no claims. | 1 claim-extraction call: HTTP 429 `RESOURCE_EXHAUSTED`, typed `MODEL_UNAVAILABLE`, quota exhausted, `retryable=false`, 0.133 s. Workflow 0.214 s; wall 0.226 s. No provider-reported version for the failed call. |

Case-level results and call records are in `runtime/eval/3174cec9ee434b568b9ce547f8e9d375.json`; the original case-1 workflow report is in `runtime/eval/3174cec9ee434b568b9ce547f8e9d375-case-1.sqlite3`. Cases 3 and 4 were not retried.

## Previous mailbox-enabled ACP workflow

The requested local three-agent `demo aerobeat` was run with `ADPROOF_MAILBOX_ENABLED=1`, `GEMINI_MODEL=gemini-3.5-flash`, and the configured Gemini/Sentry bindings. The local ACP response for session `152a5abf-07cf-45a1-b6d2-0dc1235697fe` reported audit `cdcd5fc38c504255b0de3e050a7facd2`, final decision `HUMAN_REVIEW`, and workflow `COMPLETED` (the result was returned, not the campaign fully verified). The audit's original decision was `HUMAN_REVIEW`, with no claims. Image inspection succeeded and reported `gemini-3.6-flash`; the original verification then failed with retryable HTTP 503 `MODEL_UNAVAILABLE` (`quota_exhausted=false`). Total workflow time was 21.879 s. There was no repair proposal and no revised audit, so repair → re-verification was not reached. The client reported `contains_original_repair_reverify=false`.

The orchestrator log confirms mailbox-client startup, local server port 8100, and no `Endpoint configuration overrides mailbox setting` warning. Local verifier/remediator endpoints and resolver were active; the response returned through the original ACP session. The latest SDK run again said the mailbox must be created through the inspector and warned that contract registration needs funds; public discoverability remains unproven. All agent processes were stopped by the workflow script before this report was written.

## User-reported case-1 repair workflow

The user reported a completed three-agent `demo aerobeat` run. The original audit correctly returned `FIX_REQUIRED`. The repair proposal was: “AeroBeat headphones are splash-resistant for everyday use. Get up to 30 hours of battery life with noise cancellation off. Now $60—25% off!” Re-verification returned `HUMAN_REVIEW` because Gemini quota was exhausted with HTTP 429; the workflow was `PARTIAL` and the repair was correctly marked unverified. The reported audit was `b3d4f79e1cf44d7da6bc7fe5d90e4c20`, client session `cacab77b-5206-4f44-a4a5-7108c0506f20`, and served model `gemini-3.6-flash`. No timing, call count, or local artifact path was provided with this report.

## Agentverse mailbox and Sentry validation (2026-10-18)

The user signed in to Agentverse in the Devin VM browser and selected Inspector → Connect → Mailbox for orchestrator `agent1q0lpgrz6c80h2n5ns0vw5sq0wtrp8gkm92x3pl6n5hwru7z0f47977ntemy`. The orchestrator log then reported `[mailbox]: Successfully registered as mailbox agent in Agentverse`. The user queried `https://agentverse.ai/v1/almanac/agents/agent1q0lpgrz6c80h2n5ns0vw5sq0wtrp8gkm92x3pl6n5hwru7z0f47977ntemy`; the response showed `status: active`, `type: mailbox`, endpoint `https://agentverse.ai/v2/agents/mailbox/submit`, 2 protocols, and expiry `2026-11-16T23:01:11Z`.

Almanac on-chain contract registration is not required. In `uagents 0.26.1`, `DefaultRegistrationPolicy` registers through the Almanac API first (which succeeded) and then swallows `InsufficientFundsError` for the contract step. The wallet had no funds; none were spent or requested.

The user also confirmed ingestion in their Sentry account. The full ASI:One workflow remains pending until the user reports a test.
