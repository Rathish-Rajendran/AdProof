# AdProof

AdProof generates ads from a company's own data, then independently checks every claim and applicable platform policy. If the verifier returns `FIX_REQUIRED`, it makes at most one copy-only fix and re-checks it before returning a scored JSON result. Nothing is auto-published; AdProof is not legal advice or platform approval.

## Architecture

![AdProof architecture](docs/images/architecture.png)

1. The user sends an ad prompt to the Agentverse mailbox.
2. The orchestrator parses the request and selects the workflow.
3. The generator retrieves company data and drafts the ad.
4. The verifier checks claims, evidence, image context, and active policies.
5. If the decision is `FIX_REQUIRED`, the remediator proposes at most one copy-only fix.
6. The verifier independently re-checks the revised copy against the original evidence.
7. The orchestrator scores the final audit with deterministic checks.
8. AdProof returns a compact JSON result to the original chat.

| Agent | Port | Model |
|---|---:|---|
| Orchestrator | 8100 | No model call; coordinates the workflow |
| Verifier | 8101 | `gemini:gemini-3.1-pro-preview` for claim extraction and evidence assessment |
| Remediator | 8102 | `gemini:gemini-3.5-flash` |
| Generator | 8103 | `gemini:gemini-3.5-flash` |

See [architecture details](docs/architecture.md) for component boundaries.

## Key design rules

- The model writes and reads; code decides.
- The verifier retrieves its own evidence and requires exact quotes.
- There is at most one repair, and every repair is re-checked.
- The system does not allow invented numbers.
- Minors, Meta, and out-of-scope requests go to human review.

## Output

This real result is shortened to two of the six claims in `runtime/samples/simple_generate.json`.

```json
{
  "audit_id": "1a283c316022444bb1d95e0066111de7",
  "needs_review": false,
  "confidence": 100,
  "summary": "Ready to run: all 6 claims are backed by company data; 2 Google Ads rules passed.",
  "ad": {
    "platform": "google_ads",
    "headlines": ["AeroBeat AB-01 Headphones", "Wireless Over-Ear Headphones", "Now $60 Regular Price $80"],
    "descriptions": [
      "AeroBeat AB-01 wireless over-ear headphones. Get up to 30 hours battery life with ANC off.",
      "Save 25% on AeroBeat AB-01 headphones. IPX4 splash-resistant with 1-year limited warranty."
    ],
    "final_url": "https://aerobeat.example/products/ab-01"
  },
  "compliance": "OK",
  "claims": [
    {
      "claim": "You get up to 30 hours of battery life with ANC off.",
      "quote": "Battery life is up to 30 hours with active noise cancellation (ANC) off",
      "source": "AeroBeat AB-01 headphones product page › Battery"
    },
    {
      "claim": "The AeroBeat AB-01 headphones are IPX4 splash-resistant.",
      "quote": "The AB-01 is splash-resistant for everyday use and has an IPX4 rating.",
      "source": "AeroBeat AB-01 headphones product page › Durability and connectivity"
    }
  ]
}
```

`confidence` is the share of deterministic checks passed. A result is ready at 95 or more only when the final audit is `PASS`; confidence is not a probability. `compliance` is `"OK"` or a list of plain-language issues.

## Models

| Job | Default model | Why |
|---|---|---|
| Claim extraction | `gemini:gemini-3.1-pro-preview` | Stronger verifier model for the difficult evidence-judgment step. |
| Evidence assessment | `gemini:gemini-3.1-pro-preview` | Separate from the writer to reduce shared blind spots. |
| Ad generation | `gemini:gemini-3.5-flash` | Fast, lower-cost writing. |
| Copy remediation | `gemini:gemini-3.5-flash` | Fast, lower-cost fixing, with numeric edits checked by code. |
| Image inspection | `gemini:gemini-3.5-flash` | Reads the supplied image. |
| Default | `gemini:gemini-3.5-flash` | Baseline for jobs without a specialized default. |

The Pro model is a preview and adds latency; writing and fixing use Flash for speed and cost. Override a job with its `ADPROOF_MODEL_*` setting. Optional Ollama routing is supported; when Ollama is the default, claim extraction and evidence assessment inherit that default.

## Company data and RAG

- The included corpus has 23 synthetic AeroBeat Markdown documents.
- Markdown is split into heading-aware chunks; retrieval combines BM25 and bge-small embeddings with reciprocal-rank fusion (RRF).
- Chunks and embeddings are stored in local SQLite at `runtime/corpus_index.sqlite3`.
- Add a company's Markdown under `data/corpus/<company>/` with YAML front matter for `doc_id`, `title`, `url`, `doc_type`, and (for product-specific docs) `product_id`. Set the product page's `url` to the intended `final_url`.

## Policies

Google Ads has two active enforcement rules. The verbatim reference library has 19 entries: Google Ads 7, Meta 3, FTC 6, and UK ASA 3.

Run `uv run python scripts/verify_policy_library.py` to check stored excerpts against their official sources. See the [policy library](docs/policy-library.md) for provenance and excerpts.

Meta has no active rules yet: its verified references do not establish a supported product-claims predicate for automated enforcement, so Meta requests require human review.

## Run it locally

Prerequisites: Python 3.11, [uv](https://docs.astral.sh/uv/), and a billed Gemini API key for live model calls. Sentry is optional.

From a fresh checkout, run these from the repository root:

```sh
uv sync
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY.
set -a; source .env; set +a
uv run pytest -q
uv run python -m adproof.generate "Generate a Google Ads ad for AeroBeat AB-01 headphones for US adults"
uv run python -m adproof.generate "Generate a Google Ads ad for AeroBeat AB-01 headphones for US adults" --offline
bash scripts/run_all.sh
```

The non-offline generation command uses the configured model. `--offline` exercises the in-process workflow with fake models and no key. The agent script starts the four local agents and remains in the foreground.

## Use it from ASI:One

1. Set `ADPROOF_MAILBOX_ENABLED=1` in `.env`, export it in the shell, and start the agents.
2. Find the inspector link printed in `runtime/orchestrator.log`; open it in a browser on the same machine as the orchestrator.
3. Choose **Connect → Mailbox**. The “insufficient funds” Almanac warning is harmless; mailbox API registration does not require on-chain funds.

In ASI:One, address the orchestrator or mention its address, then send:

```text
help
generate <prompt>
demo aerobeat
report <audit_id>
```

Try these generation prompts:

- `generate Generate a Google Ads ad for AeroBeat AB-01 headphones for US adults` → expected ready result.
- `generate Generate an ad for AB-02 Pro for teens` → expected needs review.

## Docker

Run `docker compose up --build -d`. To use the optional local Ollama profile, run `docker compose --profile ollama up --build -d` and configure the model overrides. Keep the existing `ORCHESTRATOR_SEED`, `VERIFIER_SEED`, `REMEDIATOR_SEED`, and `GENERATOR_SEED` values stable to preserve agent identities. See [setup and operations](docs/setup.md).

## Troubleshooting

| Symptom | What to do |
|---|---|
| `401 MODEL_AUTH` from a stale key | Update `.env`, re-export it, and restart the agents. |
| `429` model response | Check provider quota and billing. |
| Reply too large | This transport issue is fixed and should no longer happen. |
| No reply in ASI:One | Check the `@` mention/recipient and confirm the mailbox is connected. |
| `HUMAN_REVIEW` on Meta | Expected; Meta enforcement rules are not active yet. |

## Project layout

```text
adproof/          Application, verifier, generator, RAG, and orchestration
agents/           Four uAgents entry points
data/corpus/      Synthetic company documents
data/policies/    Active rules and verbatim reference library
docs/             Architecture, setup, policy, and validation details
scripts/          Runtime preparation and verification utilities
tests/            Offline tests
runtime/          Local index, logs, reports, and private seeds (ignored)
```

## Limits and scope

- AdProof does not publish ads, provide legal advice, or guarantee platform approval.
- Results cover only the supplied evidence and implemented policy checks; they are not a complete review of every law or platform rule.
- Images are never edited. Repairs change copy at most once; Meta, minors, and out-of-scope requests require human review.
