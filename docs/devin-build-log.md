# Devin build log

## 2026-10-18 — M0 through M4 implementation

- Baseline repository commit `b580bd3` contained only the initial README and ignore rules; no live app or registered identities were present in this checkout.
- Copied the authoritative build brief, reference plans, and unchanged bundled MOCK prototype into the repository.
- Tried the specified `uagents==0.25.5` baseline. The resolved install uses `uagents-core==0.4.12`; it provides `ChatMessage`, `ChatAcknowledgement`, the chat cards module, and the public `handle_messages_concurrently` constructor argument. No SDK bump was needed.
- Copied the lead-reviewed policy catalog and pack byte-for-byte. The loader accepts missing source provenance on DRAFT rules and requires provenance on ACTIVE entries; the refresh utility reports excerpt drift without modifying reviewed policy.
- Added a strict domain layer, pure decision/report-selection functions, generated JSON Schema artifacts, shared specialist envelopes, task correlation, local agent endpoints, model/source/image infrastructure, verification/remediation, and a single-repair workflow with same-image re-verification.
- Added synthetic AeroBeat image variants and page content, an explicit MOCK CLI, a live Gemini smoke CLI, and local health/supervision scripts.

## Validation and push

- Pushed the implementation to `devin/adproof-full-build` in focused commits; no PR was opened and no CI was watched.
- `uv run pytest -q`: 25 passed. `uv run ruff check .`: all checks passed. Offline preflight, MOCK demo, schema export, legacy tests (24 passed), and legacy server startup passed.
- The M1 client proved both a delayed specialist response and watchdog `TASK_TIMEOUT` return through the original ACP session UUID. Local routing used loopback REST endpoints and a `RulesBasedResolver`.
- Gemini was called only as `gemini-3.8-flash`. The earlier pinned **correct-copy case 4** live smoke completed `PASS` with five model calls (image inspection 3.80 s and 41.39 s; claim extraction 10.70 s; evidence assessment 4.41 s; the blurry image call returned typed `MODEL_UNAVAILABLE` in 3.22 s). Subsequent retry calls returned typed `MODEL_UNAVAILABLE` with HTTP 429. No model substitution or fixture fallback occurred. This predates the current M5–M7 edits and is not evidence for the unsafe-copy case 1.
- The three-process live workflow reached verification but could not complete repair/reverification because Gemini returned typed HTTP 503 errors. A model-failure path initially exposed an uninitialized evidence map; it was fixed and regression-tested. No full live repair success is claimed.
- `SENTRY_ENVIRONMENT=devin-dev` was bound for smokes. Local traceparents were emitted, but Sentry account ingestion was not independently verified. Local agents emitted inspector URLs and Almanac API registration success; unfunded contract-registration warnings appeared. No public deployment or ASI:One registration was attempted.
- Public fixtures are pinned in `data/fixtures/demo_manifest.json`; `curl` confirmed HTTP 200, expected MIME types, and matching SHA-256 hashes for all five assets. The demo campaign uses the immutable URLs from fixture commit `535748301de3aefdf3510a2f9136f865900f2657`.

## User-approved Gemini default change

The user approved changing the configurable default from `gemini-3.8-flash` to `gemini-3.5-flash` after `gemini-3.8-flash` returned HTTP 429 `RESOURCE_EXHAUSTED` due to quota exhaustion on this key. The API-reported served model version is recorded separately from the configured ID; the provider reports `gemini-3.6-flash` for this selection. No prompt changes or silent model substitutions are made.

The first post-switch live evaluation used 8 of 40 allowed calls: cases 1 and 2 matched expected decisions; cases 3 and 4 stopped on non-retryable HTTP 429 quota errors. Case 1's decision was correct, but its repair workflow was partial due to equivalent numeric formatting being rejected; the deterministic validator was corrected with an offline regression test. The mailbox-enabled ACP run reached image inspection but hit HTTP 503 during verification, before repair or re-verification. Exact outcomes are in `docs/validation-status.md`.

## User-reported case-1 repair workflow

The user reported that the original case-1 audit correctly returned `FIX_REQUIRED`. The proposed repair was “AeroBeat headphones are splash-resistant for everyday use. Get up to 30 hours of battery life with noise cancellation off. Now $60—25% off!” Re-verification returned `HUMAN_REVIEW` after Gemini quota exhaustion (HTTP 429); the workflow was `PARTIAL` and the repair remained unverified. Audit `b3d4f79e1cf44d7da6bc7fe5d90e4c20`, client session `cacab77b-5206-4f44-a4a5-7108c0506f20`, served model `gemini-3.6-flash`. This is user-reported evidence; no local run or artifact was available.

## 2026-10-18 UTC — ASI:One testing

- At 03:20 UTC, the user's `help` reached the orchestrator mailbox, but the reply failed with `Unable to resolve destination endpoint for agent: agent1qdsz25p7…`. The orchestrator had a rules-only resolver. The user pushed `3dafa38` with `LocalFirstResolver` in `agents/common.py`, trying local rules before `GlobalResolver` for the public orchestrator.
- At 03:23 UTC, the reply arrived but raised `ValueError`: ASI:One includes the leading `@agent…` mention in the message text. The user pushed `afc5774` with `strip_leading_mentions` in `agents/orchestrator/main.py`.
- At 03:37 UTC, `@<orchestrator address> help` returned the command list in ASI:One. The user's screenshot showed a reply from `adproof-orchestrator`.
- At 03:38 UTC, ASI:One `demo aerobeat` reached the three-agent workflow. Audit `c5fc4813b2d041f890a02f2f5cb7cba4` completed in 5.31 s. Image inspection succeeded with served model `gemini-3.6-flash`; verifier Gemini HTTP 429 quota exhaustion led to final `HUMAN_REVIEW`, workflow status `COMPLETED`, `repair_verified=false`, and no repair. Transport/discovery/chat passed, but the full live FIX_REQUIRED → repair → re-verify gate is PARTIAL due to the free-tier quota.
- At 04:05 UTC, an ASI:One `demo aerobeat` attempt returned `MODEL_AUTH` HTTP 401 because the agents were running with a stale Gemini key. The user updated the key; Devin verified it with a real call that reported served model `gemini-3.6-flash`, then restarted the agents.
- At 04:13 UTC, ASI:One `demo aerobeat` passed through the Agentverse mailbox and all three agents. Audit `fb22bf8564314496a3767479ee19d842` completed in 19.9 s. The original audit was `FIX_REQUIRED` with exactly four issues: one `PRICE_DISCOUNT_MISMATCH` and two `AD_LANDING_PAGE_CONTRADICTION` issues, each carrying `GADS_MISLEADING_AD_DESIGN_AD_LANDING_INCONSISTENCY`, plus `UNVERIFIED_ENDORSEMENT`. Claims were waterproof `CONTRADICTED`, 48-hour battery `CONTRADICTED`, “Recommended by 1,000 athletes” `INSUFFICIENT_EVIDENCE`, `$60` `SUPPORTED`, and 50% off `CONTRADICTED`. The repair proposal was “AeroBeat headphones are splash-resistant for everyday use. Get up to 30 hours of battery life with noise cancellation off. Now $60—25% off!” Re-verification hit Gemini HTTP 429 quota exhaustion; final decision was `HUMAN_REVIEW`, workflow `PARTIAL`, and `repair_verified=false`. The three-agent verify → repair → reverify and full primary ASI:One gates remain PARTIAL; only live re-verification remains unproven.
- The user reports 108 tests after commit `67c3237`. This docs-only update did not rerun tests or make Gemini calls. The remaining live step is to restore quota (for example, enable billing) and resend `demo aerobeat`; then run `docker compose up` on an always-on host with the same persistent `runtime/` seeds to preserve the address and mailbox.
