# Setup

Use Python 3.11 and `uv sync --frozen`. Copy `.env.example` to a private `.env` only for local use; never commit it. `GEMINI_API_KEY` enables opt-in paid inference. `SENTRY_DSN` enables telemetry ingestion but is not required for offline operation.

Run the offline suite with `uv run pytest -q` and static checks with `uv run ruff check .`. Use `uv run python -m adproof.demo --mode mock` for the explicitly labeled fixture demonstration. Agent worker commands are listed in `agents/*/README.md`.

The local supervisor starts verifier, remediator, and orchestrator at loopback ports 8101, 8102, and 8100, respectively:

```sh
uv run python scripts/prepare_runtime.py
bash scripts/run_all.sh
```

The supervisor creates persistent seeds only when absent, writes public addresses separately, checks all three `/health` endpoints, and stops the child processes on Ctrl-C. It does not enable mailbox registration by default. To verify cross-handler ACP replies and watchdog timeouts against an actual client agent, run `bash scripts/run_transport_proof.sh` with `GEMINI_API_KEY` bound in the environment; the test-only probe does not invoke Gemini.
