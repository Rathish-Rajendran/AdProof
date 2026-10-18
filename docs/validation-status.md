# Validation status

Only executed checks may be marked PASS. This file is updated with exact commands and results during validation.

| Gate | Status | Evidence |
|---|---|---|
| Offline install, tests, lint, schemas | PASS | `uv sync --frozen` succeeded; `uv run pytest -q` — 130 passed; `uv run ruff check .` — all checks passed; `uv run ruff format --check .` — 87 files already formatted. `scripts/export_schemas.py` regenerated the JSON Schema artifacts and the generated-schema test passed. |
| Docker Compose configuration | PASS | `docker compose config -q` and `docker compose --profile ollama config -q` passed using a temporary `.env` copied from `.env.example`; the full stack was not started. |
| Offline preflight and MOCK compatibility | PASS | Latest `uv run python -m adproof.preflight --offline` passed. Latest explicit MOCK demo reported `FIX_REQUIRED` for the unsafe case-1 copy with synthetic claims and arithmetic; it is not live model evidence. Legacy MOCK suite/server were validated before these changes. |
| Optional local Ollama evaluations | PARTIAL | Historical Qwen 3B per-job evaluation mostly returned `HUMAN_REVIEW`; the 7B run was stopped for latency after cases 1–2 also returned `HUMAN_REVIEW`. Gemini is now the default; local Ollama remains opt-in. Details and artifact paths follow below. |
| Secret-safe artifacts and runtime state | PARTIAL | `.env.example` contains names only; runtime seed/address/database paths are gitignored. No dedicated secret-scanner run was performed. |
| Contracts, decisions, evidence, arithmetic, safety, store, and repair tests | PARTIAL | Offline unit tests cover strict contracts, all report-selection branches, quote validation, price arithmetic, policy provenance, SSRF/image checks, store behavior, and remediator validation; not every §9 scenario is implemented. |
| Gemini live evaluation cases 1–4 | PARTIAL | Gemini run `runtime/eval/3174cec9ee434b568b9ce547f8e9d375.json`, configured `gemini-3.5-flash`, budget 40, 8 calls used. Cases 1–2 matched expected decisions; cases 3–4 returned non-retryable quota `MODEL_UNAVAILABLE` (HTTP 429) and `HUMAN_REVIEW`. Detailed claims, arithmetic, call latencies, and artifact notes follow below. Successful call records reported `gemini-3.6-flash`; no fallback or model substitution. |
| Three local agents and correlated specialist transport | PASS | Three local agent processes used explicit loopback endpoints and the `RulesBasedResolver`; verifier fetched the pinned public source. Local health/status and message correlation were exercised. |
| ASI:One JSON-only result reply | PASS | The current response is one pretty-printed JSON block, based on the user-provided real Gemini sample `runtime/samples/8fef0a98.md`; no result card or action buttons are shown. The `report <audit_id>` and `status <audit_id>` text commands remain listed in help. |
| Delayed reply and watchdog preserve original ACP session | PASS | Mailbox-enabled run (`ADPROOF_MAILBOX_ENABLED=1`) proved delayed specialist and watchdog `TASK_TIMEOUT` replies reached session `9e81490b-bb9f-4945-93ec-5afdf004f80f`. `runtime/orchestrator.log` confirms mailbox client startup and no `Endpoint configuration overrides mailbox setting` warning; local proof passed. The orchestrator mailbox was subsequently confirmed active in Agentverse on 2026-10-18; see details below. |
| Three-agent verify → repair → reverify against live Gemini | PASS | User-reported Agentverse mailbox run `d29f13abaff94be5a6f23d8ce613055f` completed the original four-issue `FIX_REQUIRED` audit, one repair, independent `PASS` re-check, and final `PASS` with `repair_verified=true` in about 19.4 s. |
| Agentverse orchestrator mailbox | PASS | User connected the orchestrator mailbox and confirmed active Almanac API registration on 2026-10-18. The response showed `status: active`, `type: mailbox`, the mailbox submit endpoint, 2 protocols, and expiry `2026-11-16T23:01:11Z`; see details below. |
| Almanac on-chain contract registration | NOT REQUIRED | The `uagents 0.26.1` `DefaultRegistrationPolicy` registers through the Almanac API first, then swallows `InsufficientFundsError` for the contract step. The wallet was unfunded; no funds were spent or requested. |
| ASI:One help round-trip | PASS | At 03:37 UTC, `@<orchestrator address> help` returned the command list in ASI:One; the user's screenshot showed the reply from `adproof-orchestrator`. |
| Full primary ASI:One workflow | PASS | The latest user-reported Gemini run passed end to end through the Agentverse mailbox: original audit, one copy-only repair, independent re-check, and final verified `PASS`. The local Ollama evaluation remains separate and showed quality gaps. |
| Sentry trace/log ingestion | PASS | User confirmed ingestion in their Sentry account on 2026-10-18. Earlier traceparents were emitted for the live smoke (`64dbe042f73e44fcb74fd2ecb377fd73-8a8c2d0975399b0c-1`), three-agent workflow (`3dfb854a77e9433a94314c9c598d6376-b0c73e1b57ea65b9-1`), and mailbox demo (`66d8628ea5da4d7fb4e90934ad90aab9-b1a24a7d2180bdf1-0`). |
| Intended judging runtime remains available | PENDING | Human runtime action. |
| Public README setup, scope, examples, and real agent links | PARTIAL | Setup and scope are documented; only local derived agent addresses exist in ignored `runtime/agents.json`. No public agent links are available. |
| Baseline and hackathon provenance | PASS | Master prompt, reference plans, and unchanged legacy MOCK bundle are included; legacy tests and server command passed. |
| Pull request against verified base | PENDING | Lead opens PR. |

Runtime seeds remain only in ignored `runtime/` files and are not recorded here.

## Gemini default and per-job routing

Gemini (`gemini:gemini-3.5-flash`, served as `gemini-3.6-flash` in live calls) is the current default for all jobs and requires a billed `GEMINI_API_KEY`. Ollama with `qwen2.5vl:3b` for image inspection and `qwen2.5:3b` for text jobs is an optional local mapping; prior 3B runs mostly ended in `HUMAN_REVIEW`. The 7B vision/text pair is a higher-capacity local option, but slower on CPU; its partial run below did not establish a quality improvement. On the user's CPU-only 8-core, 31 GB host, the `qwen2.5vl:3b` probe read the only-$49 image correctly in 42 seconds including model load and split unsafe copy into four correct atomic claims in 10 seconds. `gemma3:4b` was also correct but took 71 seconds and 46 seconds, respectively; these are single-machine observations, not benchmarks. Small local models may be less accurate than Gemini and slower on CPU.

### Interrupted per-job 7B evaluation

Run `78a7d6d3d53d4a08b3301f5d01bbf93e` used `ollama:qwen2.5vl:7b` for image inspection and `ollama:qwen2.5:7b` for text jobs. It was stopped for latency after case 2 completed while case 3 was in progress; there is no final evaluation JSON, and cases 3–4 have no completed results. The completed workflow reports are in `runtime/eval/78a7d6d3d53d4a08b3301f5d01bbf93e-case-1.sqlite3` and `...-case-2.sqlite3`.

| Case | Expected → actual | Claims and errors | Timing |
|---|---|---|---|
| 1 | `FIX_REQUIRED` → `HUMAN_REVIEW` | All four claims (waterproof, 48-hour battery, athlete endorsement, and 50% discount) were `INSUFFICIENT_EVIDENCE`. Four `INVALID_EVIDENCE` errors show that all four supplied quotes failed source validation. | Workflow 185.380 s. |
| 2 | `PASS` → `HUMAN_REVIEW` | Splash resistance, up-to-30-hour battery, and 25% discount claims were all `INSUFFICIENT_EVIDENCE`; three `INVALID_EVIDENCE` errors rejected the supplied quotes. | Workflow 83.552 s. |
| 3 | `FIX_REQUIRED` → incomplete | The workflow had entered `VERIFYING` when the run was stopped; no final decision or timing was recorded. | Incomplete. |
| 4 | `PASS` → not run | Not started before the run was stopped. | — |

The stopped evaluation did not write a top-level JSON artifact, so model-call records and per-job counts are unavailable. The two completed reports document the resolved per-job specs and typed invalid-evidence errors. At the time, the operator approved the faster 3B local mapping and a case-1-only live evaluation; its result is recorded below.

### Per-job 3B evaluation — case 1

Run `66161b7a70df405790ff7d8feb85e4f2` ran on 2026-10-18 with `ollama:qwen2.5vl:3b` for image inspection and `ollama:qwen2.5:3b` for text jobs. The command was `uv run python -m adproof.eval --live --cases 1 --max-model-calls 12`; it used 3 of 12 calls and completed in 93.629 s (93.637 s wall time).

| Case | Expected → actual | Claims and errors | Calls and timing |
|---|---|---|---|
| 1 | `FIX_REQUIRED` → `HUMAN_REVIEW` (`COMPLETED`) | Three extracted claims—waterproof, 48-hour battery, and athlete endorsement—were `INSUFFICIENT_EVIDENCE`; the 50%-discount claim was not extracted. The image had `UNSUPPORTED_CONTEXT`. No `INVALID_EVIDENCE` errors occurred, so evidence assessment did not return rejected quotes. No repair was proposed. | 3 calls: image inspection 38.605 s; claim extraction 32.305 s; evidence assessment 22.364 s. One call per job. |

The result shows that the fast per-job 3B configuration still does not establish the expected unsafe-ad decision quality. Its JSON report is `runtime/eval/66161b7a70df405790ff7d8feb85e4f2.json`. Case 3 was not run in this evaluation, so whether the `$49` image issue is detected by this configuration remains unverified.

## Earlier live evaluation: single-model Ollama

Run ID `e9988b07a6c44b308065df0ac7582926` ran on 2026-10-18 at 05:02:53 UTC with provider `ollama`, configured and reported model `qwen2.5vl:3b`, and a 40-call budget. It used 13 calls. All model requests returned successfully; the failures below were output-quality and validation results, not Ollama transport errors. Each case returned `workflow_status=COMPLETED`; arithmetic was empty for all four. Evidence IDs were reported valid in all cases.

| Case | Expected → actual | Claim statuses and arithmetic | Calls and timing |
|---|---|---|---|
| 1 | `FIX_REQUIRED` → `HUMAN_REVIEW` | Three extracted claims were all `INSUFFICIENT_EVIDENCE`: completely waterproof; 48-hour battery; `$60—50% off`. The athlete endorsement was not extracted. No arithmetic. Image coverage was `PARTIAL`, with `UNSUPPORTED_CONTEXT`. | 3 calls: image inspection 43.800 s; claim extraction 54.427 s; evidence assessment 32.388 s. Workflow 131.002 s; wall 131.010 s. |
| 2 | `PASS` → `HUMAN_REVIEW` | All four claims were `INSUFFICIENT_EVIDENCE`: 25% discount; not waterproof; splash-resistant; up to 30-hour battery life. No arithmetic. The verifier recorded `INVALID_EVIDENCE` for quotes on claims 2–4 and `UNSUPPORTED_CONTEXT` for partial image coverage. | 2 calls: claim extraction 40.667 s; evidence assessment 43.900 s. Workflow 84.699 s; wall 84.708 s. |
| 3 | `FIX_REQUIRED` → `FIX_REQUIRED` (decision match) | Original claims—waterproof, 48-hour battery, and `$60—50% off`—were all `INSUFFICIENT_EVIDENCE`; no arithmetic. Neither the original nor revised audit reported a `$49` image issue. The copy proposal was “AeroBeat headphones are splash-resistant but not waterproof. Get up to 30 hours of battery life with noise cancellation off. Recommended by 1,000 athletes. Now $60—50% off!”; its `changes` metadata list was empty, and the revised audit retained four unsupported-claim issues. | 6 calls: image inspection 37.719 s; claim extraction 64.564 s; evidence assessment 33.704 s; copy remediation 19.425 s; revised claim extraction 22.927 s; revised evidence assessment 33.446 s. Workflow 212.221 s; wall 212.229 s. |
| 4 | `PASS` → `HUMAN_REVIEW` | Both claims were `INSUFFICIENT_EVIDENCE`: splash-resistant; up to 30-hour battery life. No arithmetic. Image coverage was `PARTIAL`, with `UNSUPPORTED_CONTEXT`. | 2 calls: claim extraction 36.109 s; evidence assessment 48.418 s. Workflow 84.761 s; wall 84.776 s. |

Case 2 additionally shows the model/extraction mismatch: explanations said the page supported claims, but the verifier rejected model-supplied quotes that did not occur in the normalized source and safely left the claims insufficient. For case 3, the final decision matched expectation, but the `$49`-specific issue was not represented. The artifact does not persist raw image observations, so it cannot distinguish whether the model omitted the price observation or a downstream path failed to report it. The verifier receives image observations and its deterministic image-price check can flag a differing price when that observation is present; no deterministic code bug was established from this run. No prompts or default-model settings were changed.

The JSON report is `runtime/eval/e9988b07a6c44b308065df0ac7582926.json`; per-case workflow records are `runtime/eval/e9988b07a6c44b308065df0ac7582926-case-1.sqlite3` through `runtime/eval/e9988b07a6c44b308065df0ac7582926-case-4.sqlite3`.

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

The user also confirmed ingestion in their Sentry account.

## ASI:One smoke sequence (2026-10-18 UTC)

- **03:20 — First help test:** The user's `help` message arrived through the mailbox, but the reply failed with `Unable to resolve destination endpoint for agent: agent1qdsz25p7…`. The orchestrator used a rules-only resolver. The user fixed public-agent routing in commit `3dafa38` (`LocalFirstResolver` in `agents/common.py`): try local rules first, then fall back to `GlobalResolver`.
- **03:23 — Second help test:** The reply arrived but raised `ValueError` because ASI:One includes the leading `@agent…` mention in the message text. The user fixed it in commit `afc5774` (`strip_leading_mentions` in `agents/orchestrator/main.py`).
- **03:37 — Help round-trip PASS:** `@<orchestrator address> help` returned the command list in ASI:One. The user's screenshot showed the response from `adproof-orchestrator`.
- **03:38 — `demo aerobeat`:** Audit `c5fc4813b2d041f890a02f2f5cb7cba4` completed in 5.31 s. Image inspection succeeded and served `gemini-3.6-flash`. The verifier then received Gemini HTTP 429 quota exhaustion; the final decision was `HUMAN_REVIEW`, workflow status `COMPLETED`, `repair_verified=false`, and no repair was produced. Thus transport/discovery/chat passed, but the full live FIX_REQUIRED → repair → re-verify gate is **PARTIAL** because the free-tier quota blocked verification.
- **04:05 — Credential recovery:** An ASI:One `demo aerobeat` attempt returned `MODEL_AUTH` HTTP 401 because the agents had a stale Gemini key. The user updated the key; Devin verified it with a real model call reporting served version `gemini-3.6-flash`, then restarted the agents.
- **04:13 — `demo aerobeat`:** Through the Agentverse mailbox and all three agents, audit `fb22bf8564314496a3767479ee19d842` completed in 19.9 s. The original audit was `FIX_REQUIRED` with exactly four issues: one `PRICE_DISCOUNT_MISMATCH` and two `AD_LANDING_PAGE_CONTRADICTION` issues, each with policy reference `GADS_MISLEADING_AD_DESIGN_AD_LANDING_INCONSISTENCY`, plus one `UNVERIFIED_ENDORSEMENT`. Claims were: waterproof `CONTRADICTED`; 48-hour battery `CONTRADICTED`; “Recommended by 1,000 athletes” `INSUFFICIENT_EVIDENCE`; `$60` `SUPPORTED`; and 50% off `CONTRADICTED`. The repair proposal was “AeroBeat headphones are splash-resistant for everyday use. Get up to 30 hours of battery life with noise cancellation off. Now $60—25% off!” Re-verification then hit Gemini HTTP 429 quota exhaustion, so the final decision was `HUMAN_REVIEW`, workflow `PARTIAL`, and `repair_verified=false`. At that point, only live re-verification remained unproven; the subsequent successful run is documented above.

## Subsequent user-reported live Gemini run

Through the Agentverse mailbox and all three agents, audit `d29f13abaff94be5a6f23d8ce613055f` completed in about 19.4 s: original `FIX_REQUIRED` with four issues, one copy-only repair, independent re-check `PASS`, final `PASS`, and `repair_verified=true`.

Remaining human step: run `docker compose up` on an always-on host using the same persistent `runtime/` seeds so the agent address and mailbox remain valid.
