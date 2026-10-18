# Local agents

The verifier and remediator accept authenticated `SpecialistTask` messages from the orchestrator address derived from the private runtime seed file. The orchestrator exposes a loopback health endpoint and uses `RulesBasedResolver` to route all three processes to their local `/submit` endpoints.

Prepare stable local identities, then start the three processes with `bash scripts/run_all.sh`. The script waits for each `/health` endpoint and stops the children on Ctrl-C. It prints only public addresses; the seed file is mode `0600` under the ignored runtime directory. Mailbox registration is off by default.

For the async ACP session proof, set `ADPROOF_TRANSPORT_PROBE=1` and run `bash scripts/run_transport_proof.sh`. The probe sends one delayed specialist result and one deliberately omitted response; the client compares the delivered session UUID with the original intake session. It is disabled in normal runs.

`GEMINI_API_KEY` is required by the orchestrator at startup and by specialist workers when they process business tasks. `SENTRY_DSN` is optional; set `SENTRY_ENVIRONMENT=devin-dev` for a live trace smoke. No agent endpoint performs ad publishing or platform certification.
