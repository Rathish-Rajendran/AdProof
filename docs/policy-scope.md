# Policy scope

AdProof is a technical preflight prototype, not legal advice, legal review, platform certification, policy approval, or a safety guarantee. The current named policy scope is Google Ads, US, English, explicitly adult-targeted general consumer electronics. Applicability is evaluated separately from whether a factual claim is supported.

The reviewed pack is `google_ads_us_electronics_v1`. Exactly two rules are ACTIVE; both have engineering (not legal or human policy) review and FIX enforcement:

1. `GADS_MISLEADING_AD_DESIGN_AD_LANDING_INCONSISTENCY` — applicable ad/landing-page inconsistency checks.
2. `GADS_UNRELIABLE_CLAIMS_INACCURATE_CLAIM` — implemented inaccurate-claim checks.

These are narrow implemented checks, not a comprehensive platform-policy engine. Other catalog entries remain DRAFT or DISABLED and are never enforced as violations. FTC material is DRAFT because the primary sources were unretrievable in the reviewed source collection and have no verified excerpt/hash/retrieval date. DRAFT data does not establish a policy violation. Missing, stale, or unreviewed required rules make policy coverage PARTIAL and require review. The pack freshness default is seven days.

Unsupported athlete endorsements are evidence findings (insufficient substantiation), not an FTC rule violation. Likewise, a white coat is an image observation—not proof of professional identity, consent, or endorsement—and the system does not impose a universal AI-generated-content label.

The catalog excerpts, hashes, applicability, engineering-review records, and source timestamps are authoritative data. `uv run python scripts/refresh_policy_sources.py` reports drift for ACTIVE excerpts; it never silently edits the catalog. Broader legal interpretation, human/legal review, enforcement, real ad delivery, and many policy categories remain outside the implementation.
