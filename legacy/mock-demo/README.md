# AdProof: local orchestration demo

This demo shows Person 1's part of AdProof: receiving a campaign, coordinating specialists, tracking each message, recovering from failures, and independently verifying a proposed repair. It runs locally with mock specialist responses, so you can explore the workflow before connecting your teammates' implementations or sponsor services.

**Execution mode: `MOCK`.** No API keys, paid services, or external accounts are required. The demo does not connect to Gemini, Agentverse, ASI:One, Sentry, or Devin. Its campaign evidence is fictional and its decisions are demonstrations, not compliance assessments.

## Run it

Requirements: Python 3.11 or newer. There are no third-party dependencies.

```sh
cd /Users/rathish/Projects/adproof
python3 -m adproof --port 8765 --open
```

The `--open` option launches your default browser. Without it, open the local URL printed in the terminal. The server binds to the local computer by default. Stop it with `Ctrl+C`.

```sh
python3 -m unittest discover -s tests -v
```

Audits are held in memory. Restarting the server clears them.

## Try it in five minutes

1. Select the **copy repair** scenario and run an audit. Inspect the original `BLOCK` decision, the proposed copy, and the independent re-audit that produces `PASS`.
2. Open the trace and message inspector. Follow the same audit through inspection, verification, repair, and re-verification. Notice the correlation information connecting requests and responses.
3. Run **unsafe image**. The copy can be repaired, but the image still contains unsafe claims, so the final result remains `BLOCK`.
4. Run **verifier timeout**. Inspect the retry and the final `HUMAN_REVIEW` outcome. Compare it with **transient retry**, which succeeds after one retry.
5. Run **reverification timeout**. The original `BLOCK` must remain visible; an unverified repair must never turn it into `PASS`.
6. Edit the campaign copy and run again. Inspect the raw JSON to see the input and the resulting report. These are small deterministic mock rules, so arbitrary text will not receive production-quality analysis.

## What the scenarios prove

| Scenario | Expected behavior | Orchestration lesson |
| --- | --- | --- |
| `copy_repair` | Initial `BLOCK`, repaired `PASS` | A new verification result is required before clearing a block. |
| `unsafe_image` | Initial `BLOCK`, repaired `BLOCK` | Editing text does not fix claims embedded in the image. |
| `safe_campaign` | `PASS`, no repair | A clean campaign can finish without unnecessary specialist calls. |
| `verifier_timeout` | One retry, then `HUMAN_REVIEW` | Missing verification is not evidence of safety. |
| `reverification_timeout` | Initial `BLOCK` preserved | A failed final check cannot erase a known problem. |
| `transient_retry` | One retry, then completion | Retry a temporary failure with a bounded policy. |

The mock image, landing-page evidence, and specialist responses are fixtures. The demo does not fetch or analyze an actual landing page or image.

## Your responsibility as Person 1

You own the coordination layer. Keep these behaviors when the mock specialists are replaced:

- Validate campaign input and create an audit identifier.
- Send the correct input to each specialist in the correct order.
- Match every response to its audit, request, and workflow stage.
- Record state changes, attempts, durations, errors, and messages.
- Retry only within the configured limit and finish safely when a required service fails.
- Preserve the initial decision separately from the result of re-verification.
- Return one consistent report to the interface that requested the audit.

Person 2 will supply the real evidence and policy verification. Person 3 will supply image inspection and repair generation. The visible intelligence in this demo is deliberately mocked; your coordination and recovery logic are the part being exercised.

## Workflow

```text
Campaign input
    → inspect creative
    → verify claims and evidence
    → save initial decision
    → if a repair is appropriate: propose repair
    → inspect repaired creative and verify it again
    → save final report
```

The repair step never decides whether its own output passes. The verifier must evaluate the repaired campaign, including any unchanged image claims. If a required check cannot complete, the report records that uncertainty.

## Code map and replacement seams

| File or directory | Purpose |
| --- | --- |
| `adproof/__main__.py` | Command-line startup and optional browser launch. |
| `adproof/server.py` | Local HTTP server and API routing. |
| `adproof/workflow.py` | Audit state, mock gateway, specialist coordination, correlation, retries, and report assembly. |
| `adproof/specialists.py` | Replaceable deterministic inspection, verification, and repair functions. |
| `adproof/fixtures.py` | Fictional campaigns, evidence, and failure scenarios. |
| `adproof/errors.py` | Errors used to exercise recovery paths. |
| `static/` | Browser interface, traces, message inspection, and JSON views. |
| `tests/` | Workflow and local API checks. |

The gateway is a Python simulation of message delivery. Its envelopes make the handoffs inspectable, but they are not live uAgents messages or the Agent Chat Protocol.

Connect the real product in this order:

1. Agree with both teammates on the input and output fields accepted by each specialist. Use the demo's captured requests and reports as concrete examples.
2. Replace the mock inspector with Person 3's image and copy inspection function.
3. Replace the mock verifier with Person 2's evidence and policy function.
4. Replace the mock repair function with Person 3's repair function. Keep re-verification in the orchestrator.
5. Add a `LiveGateway` that transports those requests to real specialist agents while preserving the workflow-facing interface.
6. Connect the user-facing orchestrator to uAgents, Agentverse, and the Agent Chat Protocol. Test the full conversation in ASI:One.
7. Send the existing audit events and errors to Sentry. Use the audit identifier to connect events across specialists.

Gemini belongs behind the inspection or reasoning adapters. Changing the model should not require rewriting the orchestration. Devin can implement these adapters and the live gateway from your agreed contracts.

## Local API

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Confirm that the local demo is running. |
| `GET` | `/api/scenarios` | List the supplied campaign scenarios. |
| `POST` | `/api/audits` | Start an audit using a scenario and campaign input. |
| `GET` | `/api/audits/:id` | Read an audit and its progress. |
| `GET` | `/api/audits/:id/report` | Read the audit report. |

Use the browser's input and raw JSON panels to inspect the exact request and response shapes. The server is a local development server, and the in-memory store is intended for this demo rather than shared deployment.

## What to give Devin for the next implementation

- This repository and your Person 1 implementation plan.
- The final specialist contracts agreed with Persons 2 and 3, including one successful and one failed response per specialist.
- The real specialist addresses or callable adapters, and a contact or owner for each.
- The intended execution order, timeout, and maximum retry count for each stage.
- The Agentverse account setup and deployment target; provide secrets through the environment or the approved secret store.
- The required report fields, decision rules, and the six scenarios above as acceptance examples.
- A definition of completion: the same scenarios work through the live gateway, and the entire user journey can run through ASI:One.

For your manual handoff, first run every scenario, inspect the messages with your teammates, and resolve any contract differences. Then supply credentials and agent registration details privately. Keep the local mock mode so all three people can continue testing while a live service is unavailable.
