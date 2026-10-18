# Validation status

Only executed checks may be marked PASS. This file is updated with exact commands and results during validation.

| Gate | Status | Evidence |
|---|---|---|
| Offline install, tests, lint, schemas | PASS | `uv sync --frozen` succeeded; `uv run pytest -q` — 25 passed; `uv run ruff check .` — all checks passed; schema export and staleness test passed. |
| Offline preflight and MOCK compatibility | PASS | `uv run python -m adproof.preflight --offline`; `uv run python -m adproof.demo --mode mock`; legacy MOCK suite — 24 passed; legacy server command started on port 8765. |
| Secret-safe artifacts and runtime state | PARTIAL | `.env.example` contains names only; runtime seed/address/database paths are gitignored. No dedicated secret-scanner run was performed. |
| Contracts, decisions, evidence, arithmetic, safety, store, and repair tests | PARTIAL | Offline unit tests cover strict contracts, all report-selection branches, quote validation, price arithmetic, policy provenance, SSRF/image checks, store behavior, and remediator validation; not every §9 scenario is implemented. |
| Live Gemini image inspections and case 1 | PARTIAL | `gemini-3.8-flash`, no fixture fallback. One run: neutral and Only-$49 inspections succeeded (3.80 s and 41.39 s); blurry inspection returned `MODEL_UNAVAILABLE` / HTTP 503 (3.22 s). Case 1 completed with PASS (claim extraction 10.70 s, evidence assessment 4.41 s; 5 calls total). Later retry returned HTTP 429 / `MODEL_UNAVAILABLE` on all three image calls. A repeated case-1 run reused the completed idempotent audit. |
| Three local agents and correlated specialist transport | PASS | Three local agent processes used explicit loopback endpoints and the `RulesBasedResolver`; verifier fetched the pinned public source. Local health/status and message correlation were exercised. |
| Delayed reply and watchdog preserve original ACP session | PASS | Both replies matched session UUID `cb0c6ae3-f88f-43cc-b57a-9a13e290547b`; delayed specialist result and `TASK_TIMEOUT` reached the same client session. |
| Three-agent verify → repair → reverify against live Gemini | BLOCKED | Attempt reached the verifier but Gemini returned HTTP 503 twice; final report was `HUMAN_REVIEW` with `MODEL_UNAVAILABLE`, and no repair/reverification occurred. An earlier smoke exposed an uninitialized evidence map on model failure; fixed and covered by a regression test. |
| Agentverse registration and ASI:One discoverability | PARTIAL | Local SDK startup emitted inspector URLs and Almanac API registration success. Contract registration warned that the agents lack funds; no public deployment or ASI:One registration was performed. |
| Full primary ASI:One workflow | PENDING | Requires the intended public runtime/account action. |
| Sentry trace/log ingestion | PARTIAL | `SENTRY_ENVIRONMENT=devin-dev`; traceparents emitted: `64dbe042f73e44fcb74fd2ecb377fd73-8a8c2d0975399b0c-1` (live-smoke case 1) and `3dfb854a77e9433a94314c9c598d6376-b0c73e1b57ea65b9-1` (three-agent workflow). SDK reported pending events; ingestion was not independently confirmed in the Sentry account. |
| Intended judging runtime remains available | PENDING | Human runtime action. |
| Public README setup, scope, examples, and real agent links | PARTIAL | Setup and scope are documented; only local derived agent addresses exist in ignored `runtime/agents.json`. No public agent links are available. |
| Baseline and hackathon provenance | PASS | Master prompt, reference plans, and unchanged legacy MOCK bundle are included; legacy tests and server command passed. |
| Pull request against verified base | NOT APPLICABLE | No PR was requested; branch was pushed without waiting for or checking CI. |

The pushed branch is `devin/adproof-full-build`. The final local live workflow returned audit `6d5ed6c0aa7e44b7b8187644f2f79a8f` as `HUMAN_REVIEW`; traceparent was emitted locally, but its ingestion was not confirmed. Runtime seeds remain only in ignored `runtime/` files and are not recorded here.
