# Policy library

`data/policies/library/` stores official policy-source snapshots as references for future retrieval. Excerpts are verbatim substrings of the normalized page returned by `adproof.infrastructure.snapshot.normalize_source`; summaries are clearly labeled paraphrases. These references do not independently establish applicability, legal conclusions, or enforcement.

Run `uv run python scripts/verify_policy_library.py` to re-fetch each source, report excerpt matches, and flag content-hash changes for review. A changed hash does not update the library automatically.

| Library file | Issuer and scope | Evidence |
|---|---|---|
| `google_ads.json` | Google Ads, US | Two excerpts from the official Misrepresentation policy. |
| `us_federal_ftc.json` | FTC, US | eCFR Parts 255 (endorsements) and 465 (reviews/testimonials). |
| `consumer_electronics_domain.json` | FTC consumer advertising references | eCFR Parts 233 (former-price comparisons) and 323 (Made in USA labels). |
| `uk_asa_cap.json` | ASA/CAP, UK | CAP Code rule 3.1; reference only, not enforced for the US product scope. |
| `meta_ads.json` | Meta Ads | The official page renders policy text in the web content view, while this VM's normalized fetch exposes only its title. No excerpt is stored and no Meta predicate is activated. |

The Meta pack is intentionally fail-closed: its required Meta reference is absent from the unchanged enforcement catalog, so Meta policy coverage is incomplete and the result must be `HUMAN_REVIEW`. The Google policy catalog and existing Google pack are unchanged. A future review may activate a predicate only after the official normalized excerpt is available and the predicate is independently shown to match it.
