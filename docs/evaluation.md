# Evaluation

Default `uv run pytest -q` is offline and uses injected model, HTTP, clock, transport, and SQLite dependencies. `tests/eval/test_cases.py` maps each of the 24 specification cases to a focused regression test elsewhere in the suite when already covered; the first four fixture schemas and routing assumptions are also validated. Offline mocks are correctness/regression tests, not a model benchmark.

## Opt-in live run

Live inference may incur charges and requires a privately configured `GEMINI_API_KEY`. The selected model is `GEMINI_MODEL` (default `gemini-3.5-flash`); no model substitution or fixture fallback occurs. Reports distinguish the configured model from provider-reported served model versions. For one attempt per case:

```sh
uv run python -m adproof.eval --live --cases 1,2,3,4 --max-model-calls 20
```

The shared model-call cap is validated to be at most 40. The runner records configured/observed model version, expected and actual decision, claim statuses, deterministic arithmetic, evidence-ID validity, call records, timings, workflow status, and typed errors as JSON beneath `runtime/eval/`. Quota exhaustion is recorded, non-retryable, and does not trigger another case attempt. A small synthetic sample cannot establish production accuracy, generalization, or legal compliance.

Latest live run (`runtime/eval/3174cec9ee434b568b9ce547f8e9d375.json`, four synthetic cases): cases 1 and 2 matched their expected decisions; cases 3 and 4 returned `HUMAN_REVIEW` after HTTP 429 quota exhaustion. The successful provider calls reported `gemini-3.6-flash` for the configured `gemini-3.5-flash`. Case 1's decision matched, but its workflow was partial because the deterministic repair validator rejected equivalent `25%`/`25.0` formatting; that validator was fixed and covered offline afterward. The mailbox ACP workflow encountered HTTP 503 before repair and re-verification. This is a small synthetic sample, not evidence of production accuracy or generalization; exact claims, call timings, errors, and artifacts are in `docs/validation-status.md`.
