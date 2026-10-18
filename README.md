# AdProof

AdProof is a bounded, evidence-backed advertising preflight prototype. It extracts objective claims from one ad image and its copy, compares them with a supplied product page and bounded evidence, identifies unsupported or contradictory claims, and may propose one minimal copy-only repair followed by an independent audit. It never edits the image.

**Scope:** Google Ads, United States, English, adult-targeted general consumer electronics. A PASS means only that the checks and sources named in that report completed; it is not legal advice, legal review, platform certification, approval, or a safety guarantee. The service does not publish ads.

## Quickstart

Python 3.11 and [uv](https://docs.astral.sh/uv/) are required:

```sh
uv sync --frozen
uv run pytest -q
uv run ruff check .
uv run python -m adproof.preflight --offline
uv run python -m adproof.demo --mode mock
```

The explicit MOCK command is an offline demonstration, not a model benchmark. For the three local uAgents workers, see [setup](docs/setup.md); `uv run python -m adproof.status` reports agent health and locally derived public addresses without exposing seeds. The public Agentverse addresses are not yet published:

| Agent | Address |
|---|---|
| Orchestrator | `PENDING: populate from runtime/agents.json after deployment` |
| Verifier | `PENDING: populate from runtime/agents.json after deployment` |
| Remediator | `PENDING: populate from runtime/agents.json after deployment` |

## MOCK and LIVE

- `MOCK` must be selected explicitly and uses deterministic fixtures.
- `LIVE` uses the configured Gemini model and real supplied HTTPS sources. Errors remain typed errors; it never falls back to fixture outputs.
- `GEMINI_MODEL` is configurable; the default is `gemini-3.5-flash`. Live inference can incur provider charges. Keep credentials in the environment or a secret manager, never in source control.
- `uv run python -m adproof.eval --live --cases 1,2,3,4 --max-model-calls 20` runs the bounded synthetic live evaluation and writes a JSON report beneath `runtime/eval/`.

## Runtime and limits

The runtime has three processes (orchestrator, verifier, remediator), local typed specialist envelopes, persistent SQLite ownership/idempotency, and optional Sentry tracing/logging. `ADPROOF_MAILBOX_ENABLED=1` enables mailbox publication for the orchestrator; it is off by default. `docker compose up --build` is the containerized option; create a private `.env` from `.env.example` first.

One campaign supports one PNG/JPEG image, one copy string, one HTTPS landing page, and up to three supplied text/HTML evidence documents. Authenticated pages, PDFs, arbitrary browsing, other locales/platforms/categories, and campaign publishing are out of scope. Unavailable evidence, unsupported context, and materially unreadable image text require review. See [policy scope](docs/policy-scope.md), [architecture](docs/architecture.md), [evaluation](docs/evaluation.md), and the [build brief](docs/build-brief/DEVIN_MASTER_PROMPT.md).
