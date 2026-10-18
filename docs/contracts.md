# Contracts and invariants

Canonical strict domain models live in `adproof.domain.models`; specialist transport envelopes live in `adproof.transport.models`. All reject undeclared fields. Generated JSON Schemas and valid examples are stored under `schemas/`; `tests/test_schema_exports.py` fails if checked-in exports drift from the models.

## Public inputs and outputs

- `CampaignInput` identifies one image, ad-copy string, landing-page URL, campaign context, optional supporting documents/product context, and `audit_only` or `repair_once` mode.
- `CreativeCandidate` records the source image hash separately from the canonical model-input hash and transformation metadata. A copy-only repair cannot mutate the frozen image.
- `VerificationRequest` is normalized, scoped, and deadline-bounded. `VerificationResult` contains claims, evidence references, issues, coverage, policy checks, typed errors, and a decision.
- `RepairResult` contains changed copy, linked issue IDs, unresolved issues, and image-edit instructions. It has no `decision` field.
- `AuditReport` records original, proposed, and revised candidates separately; the proposal is not independently verified until a fresh verifier result exists.

## Decision and evidence rules

The decision function is deterministic. An applicable, checked, ACTIVE BLOCK predicate has highest precedence; severity alone never blocks. Incomplete coverage, invalid evidence, unsupported context, processing failure, or a review issue yields HUMAN_REVIEW. Otherwise established fixable issues yield FIX_REQUIRED; no issue within complete named scope yields PASS.

Evidence quotes must be exact excerpts from retrieved normalized snapshots. Invalid quotes/IDs cannot support a claim. `SUPPORTED` maps to landing-page `MATCH`, `CONTRADICTED` to `MISMATCH`, and all other statuses remain not established. Decimal arithmetic is limited to explicitly labeled or supplied comparable prices; currency, variant, quantity, region, and conditions must match.

## Transport and identity

Specialist envelopes are size-limited and correlate audit, task, request, campaign, candidate, creative version, phase, operation, attempt, and deadline. Only the configured specialist sender is trusted. Chat message deduplication is persistent and keyed by sender/session/message ID plus payload digest. Workflow lookup and card actions require the originating owner/session; sharing an audit ID grants no access.
