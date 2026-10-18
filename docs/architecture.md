# Architecture and data flow

The application has a strict Pydantic domain layer, infrastructure adapters, specialist business modules, and a workflow orchestrator. The orchestrator owns candidate immutability, the absolute deadline, model-call budget, repair count, owner/session checks, and final report selection. The verifier produces a bounded factual audit; the remediator proposes copy changes and never returns a verdict.

## Audit pipeline

1. Validate a `CampaignInput`, retrieve and normalize the supplied HTTPS page and supporting documents, and freeze the decoded PNG/JPEG into canonical model-input bytes.
2. Inspect the frozen image for visible text and observations. Cache is image-hash/model/prompt scoped; it does not cache a verdict.
3. Extract atomic objective claims, assess them against bounded source snapshots, validate exact quotes and evidence identifiers, and apply deterministic price arithmetic and reviewed policy checks.
4. If requested and the original audit is `FIX_REQUIRED`, propose at most one copy-only repair. The original frozen image/hash is reused; the revised copy receives a fresh independent verification.
5. Select a completed revised audit only when it completed. Otherwise retain the original as the last verified candidate and label any repair unverified.

## Processes and reliability

The runtime consists of the ACP orchestrator, verifier, and remediator uAgents. Typed `SpecialistTask`/`SpecialistResult` envelopes carry audit/candidate/phase/attempt/deadline and trace context. The orchestrator checks sender and correlation fields before resolving a pending task. Local direct gateways are injectable for offline tests; the runtime uses a resolver with explicit local HTTP endpoints. Durable SQLite records bind workflows, chat deduplication, and card actions to owner/session.

HTTP retrieval is HTTPS-only, port 443, DNS/peer-public-address checked, redirect-bounded, and streamed under byte caps. Sentry instrumentation is optional, scrubs sensitive content, and is never a prerequisite for completing an audit.

## Execution modes

- `LIVE`: configured model provider (Ollama by default, Gemini optionally) and real supplied sources; provider/auth/source errors remain visible, with no fixture fallback.
- `MOCK`: explicit developer-only deterministic demo.
- `TRANSPORT_TEST`: local ACP/session-delivery verification; it does not invoke the model.

## Scope and trust

Ad copy, page text, and supporting sources are untrusted input, not instructions. Missing evidence, context mismatches, invalid quotes, incomplete policy coverage, and unreadable material image text route to review rather than PASS. See [contracts](contracts.md) and [policy scope](policy-scope.md).
