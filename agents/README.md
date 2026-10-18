# Local agents

The verifier and remediator accept authenticated `SpecialistTask` messages from the orchestrator address derived from the private runtime seed file. The orchestrator exposes a loopback health endpoint and uses `RulesBasedResolver` to route all three processes to their local `/submit` endpoints.

Prepare stable local identities, then start the three processes with `bash scripts/run_all.sh`. The script waits for each `/health` endpoint and stops the children on Ctrl-C. It prints only public addresses; the seed file is mode `0600` under the ignored runtime directory. Mailbox registration is off by default.

For the async ACP session proof, set `ADPROOF_TRANSPORT_PROBE=1` and run `bash scripts/run_transport_proof.sh`. The probe sends one delayed specialist result and one deliberately omitted response; the client compares the delivered session UUID with the original intake session. It is disabled in normal runs.

Ollama is the default model provider and must be available at `OLLAMA_BASE_URL` (default `http://127.0.0.1:11434`). Image inspection defaults to `ollama:qwen2.5vl:3b`; claim extraction, evidence assessment, and copy remediation default to `ollama:qwen2.5:3b`. The 7B vision/text pair is the higher-accuracy local option, with slower CPU inference. Per-job `ADPROOF_MODEL_*` settings accept `<provider>:<model>` specs, for example `ADPROOF_MODEL_EVIDENCE_ASSESSMENT=gemini:gemini-3.5-flash`; a Gemini-routed job requires `GEMINI_API_KEY`. Restart agents after changing the environment. `SENTRY_DSN` is optional; set `SENTRY_ENVIRONMENT=devin-dev` for a live trace smoke. No agent endpoint performs ad publishing or platform certification.
