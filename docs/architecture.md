# Architecture

AdProof separates strict domain contracts from source acquisition, image inspection, specialist verification/remediation, and orchestration. The orchestrator owns immutable candidates, deadlines, budgets, repair count, and final report selection. The verifier alone produces semantic audit decisions; the remediator proposes copy changes and never decides.

The runtime target is three uAgents processes: ACP orchestrator, verifier, and remediator. A local gateway supports offline tests, while a transport gateway uses bounded typed envelopes for specialist work. Image inspection is a local orchestrator module. Sentry is optional and must not change outcomes.

## Execution modes

- `LIVE`: configured external model and real supplied sources; errors remain errors.
- `MOCK`: explicitly selected developer demonstration only.
- `TRANSPORT_TEST`: local message-flow validation.
