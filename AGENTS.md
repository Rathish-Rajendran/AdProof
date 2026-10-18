# AdProof repository guide

The authoritative product specification is [the build brief](docs/build-brief/DEVIN_MASTER_PROMPT.md).

- Use Python 3.11 and `uv`; install from the committed lock with `uv sync --frozen`.
- Keep domain and transport models strict; export schema changes with `uv run python scripts/export_schemas.py`.
- Default tests must run offline and must not require model keys or external services.
- LIVE failures must remain typed failures; only explicit `--mode mock` may use fixture behavior.
- Never commit `.env`, generated runtime state, private seeds, user inputs, or downloaded snapshots.
- Keep the evidence scope and review requirements visible; do not describe the product as legal advice or certification.
