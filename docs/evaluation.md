# Evaluation

Default `uv run pytest -q` is offline and uses injected model, HTTP, clock, transport, and SQLite dependencies. `tests/eval/test_cases.py` maps each of the 24 specification cases to a focused regression test elsewhere in the suite when already covered; the first four fixture schemas and routing assumptions are also validated. Offline mocks are correctness/regression tests, not a model benchmark.

## Opt-in live run

Live inference may incur charges and requires a privately configured `GEMINI_API_KEY`. The selected model is `GEMINI_MODEL` (default `gemini-3.8-flash`); no model substitution or fixture fallback occurs. For one attempt per case:

```sh
uv run python -m adproof.eval --live --cases 1,2,3,4 --max-model-calls 20
```

The shared model-call cap is validated to be at most 40. The runner records configured/observed model version, expected and actual decision, claim statuses, deterministic arithmetic, evidence-ID validity, call records, timings, workflow status, and typed errors as JSON beneath `runtime/eval/`. Quota exhaustion is recorded, non-retryable, and does not trigger another case attempt. A small synthetic sample cannot establish production accuracy, generalization, or legal compliance.

Live evaluation results: **PENDING for this implementation revision**. Consult `docs/validation-status.md` for measured outcomes; do not treat the earlier M0–M4 run as current evidence.
