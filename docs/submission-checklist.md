# Human-owned submission checklist

## Verified evidence (2026-10-18)

- [x] The orchestrator mailbox is connected in Agentverse for `agent1q0lpgrz6c80h2n5ns0vw5sq0wtrp8gkm92x3pl6n5hwru7z0f47977ntemy`. The user signed in to Agentverse in the Devin VM browser, opened the orchestrator inspector, and selected **Connect → Mailbox**. The orchestrator log reported `[mailbox]: Successfully registered as mailbox agent in Agentverse`.
- [x] Devin queried `https://agentverse.ai/v1/almanac/agents/agent1q0lpgrz6c80h2n5ns0vw5sq0wtrp8gkm92x3pl6n5hwru7z0f47977ntemy`; it returned `status: active`, `type: mailbox`, endpoint `https://agentverse.ai/v2/agents/mailbox/submit`, 2 protocols, and expiry `2026-11-16T23:01:11Z`.
- [x] Sentry ingestion was confirmed by the user in their Sentry account.
- Almanac on-chain contract registration is **not required**: `uagents 0.26.1` registers through the Almanac API first, then swallows `InsufficientFundsError` for the contract step. The wallet had no funds; none were spent or requested.

## Remaining human-owned submission steps

- [ ] Confirm hackathon eligibility, team/project metadata, repository link, and submission requirements.
- [ ] Keep the three workers running on the selected always-on judging runtime; inject secrets privately and preserve the stable seed volume.
- [ ] To connect an agent mailbox, run the agent on its target machine, open the Agentverse inspector in that same machine's browser, sign in, select the agent, then click **Connect → Mailbox**. The inspector calls `127.0.0.1:8100`; opening it in a different machine's browser targets that browser machine's loopback instead of the running agent. Confirm the mailbox-registration log message and active Almanac API response rather than inferring success from local startup.
- [ ] ASI:One full workflow remains pending until the user reports a test. Once tested, send a real “hello/status” and exercise the case-1 workflow; retain a safe screenshot or shared conversation link with no credentials or private source data.
- [x] Confirm Sentry project configuration and real Tracing/Logs ingestion from an authorized account; the user confirmed ingestion in Sentry on 2026-10-18.
- [ ] Capture a short demo video, verify the actual duration, and show bounded scope, exact evidence, one copy-only repair, same-image re-verification, and any live failures honestly.
- [ ] Review the policy catalog and its two ACTIVE engineering-reviewed checks; keep FTC entries DRAFT unless their sources are retrieved and independently reviewed.
- [ ] Complete all human-owned event forms, consent/release steps, judging attendance, and submission channels.

Do not mark a checklist item complete on the basis of fixtures, mocks, local health, or an unverified deployment.
