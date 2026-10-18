# Local agents

The verifier, remediator, and generator accept authenticated `SpecialistTask` messages only from the orchestrator address derived from the private runtime seed file. The orchestrator exposes a loopback health endpoint and uses `RulesBasedResolver` to route the four processes to their local `/submit` endpoints. The generator listens on port 8103; the existing verifier, remediator, and orchestrator ports remain 8101, 8102, and 8100.

Prepare stable local identities, then start the processes with `bash scripts/run_all.sh`. The script waits for each `/health` endpoint and stops the children on Ctrl-C. It prints only public addresses; the seed file is mode `0600` under the ignored runtime directory. Mailbox registration is off by default.

For the async ACP session proof, set `ADPROOF_TRANSPORT_PROBE=1` and run `bash scripts/run_transport_proof.sh`. The probe sends one delayed specialist result and one deliberately omitted response; the client compares the delivered session UUID with the original intake session. It is disabled in normal runs.

Gemini (`gemini:gemini-3.5-flash`) is the default model for all jobs and requires `GEMINI_API_KEY` with billing enabled. Ollama with `qwen2.5:3b` for text and `qwen2.5vl:3b` for image inspection is an optional local mapping; prior 3B runs mostly ended in `HUMAN_REVIEW`. The 7B vision/text pair is a higher-capacity local option with slower CPU inference. Per-job `ADPROOF_MODEL_*` settings accept `<provider>:<model>` specs. To use local Qwen, set `ADPROOF_MODEL_DEFAULT=ollama:qwen2.5:3b` and `ADPROOF_MODEL_IMAGE_INSPECTION=ollama:qwen2.5vl:3b`; restart agents after changing the environment. `SENTRY_DSN` is optional; set `SENTRY_ENVIRONMENT=devin-dev` for a live trace smoke. No agent endpoint performs ad publishing or platform certification.

The `ADPROOF_MODEL_AD_GENERATION` purpose can override the generation job independently. The local corpus index is built lazily from `data/corpus/aerobeat/`; the specialist uses port 8103. For an in-process check, run `uv run python -m adproof.generate "<prompt>" --offline`.
