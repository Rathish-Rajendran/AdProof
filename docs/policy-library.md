# Official policy reference library

The library stores verbatim excerpts from official platform and regulator sources. Entries are reference-only unless a reviewed catalog rule explicitly enforces them. The verifier re-fetches each source, checks the excerpt, and reports source-hash changes. `normalized` is the default match mode; Meta Business Help excerpts use HTML-unescaped raw response text because the page embeds its content.

| Policy ID | Official source | Excerpts | Match mode |
|---|---|---:|---|
| `GADS_MISLEADING_AD_DESIGN_AD_LANDING_INCONSISTENCY_REFERENCE` | [Google Ads Misrepresentation](https://support.google.com/adspolicy/answer/6020955) | 1 | normalized |
| `GADS_UNRELIABLE_CLAIMS_INACCURATE_CLAIM_REFERENCE` | [Google Ads Misrepresentation](https://support.google.com/adspolicy/answer/6020955) | 1 | normalized |
| `GADS_DISHONEST_PRICING_REFERENCE` | [Google Ads Misrepresentation](https://support.google.com/adspolicy/answer/6020955) | 1 | normalized |
| `GADS_EDITORIAL_CAPITALIZATION_REFERENCE` | [Google Ads Editorial](https://support.google.com/adspolicy/answer/6021546) | 1 | normalized |
| `GADS_DESTINATION_MISMATCH_REFERENCE` | [Google Ads Destination requirements](https://support.google.com/adspolicy/answer/6368661) | 1 | normalized |
| `GADS_HEALTHCARE_PRESCRIPTION_REQUIREMENTS_REFERENCE` | [Google Ads Healthcare and medicines](https://support.google.com/adspolicy/answer/176031) | 1 | normalized |
| `GADS_PERSONALIZED_ADVERTISING_MINORS_REFERENCE` | [Google Ads Personalized advertising](https://support.google.com/adspolicy/answer/143465) | 1 | normalized |
| `META_SPECIAL_AD_CATEGORY_CAMPAIGN_SELECTION_REFERENCE` | [Meta Special Ad Categories](https://www.facebook.com/business/help/298000447747885) | 1 | raw_html_unescaped |
| `META_SPECIAL_AD_CATEGORY_REJECTION_REFERENCE` | [Meta Special Ad Categories](https://www.facebook.com/business/help/298000447747885) | 1 | raw_html_unescaped |
| `META_SPECIAL_AD_CATEGORY_AUDIENCE_RESTRICTIONS_REFERENCE` | [Meta Special Ad Categories](https://www.facebook.com/business/help/298000447747885) | 1 | raw_html_unescaped |
| `FTC_ENDORSEMENT_GUIDES_REFERENCE` | [eCFR Part 255](https://www.ecfr.gov/api/versioner/v1/full/2026-10-15/title-16.xml?part=255) | 2 | normalized |
| `FTC_CONSUMER_REVIEW_RULE_REFERENCE` | [eCFR Part 465](https://www.ecfr.gov/api/versioner/v1/full/2026-10-15/title-16.xml?part=465) | 1 | normalized |
| `FTC_DECEPTIVE_PRICING_FORMER_PRICE_REFERENCE` | [eCFR Part 233](https://www.ecfr.gov/api/versioner/v1/full/2026-10-15/title-16.xml?part=233) | 1 | normalized |
| `FTC_MADE_IN_USA_LABELING_REFERENCE` | [eCFR Part 323](https://www.ecfr.gov/api/versioner/v1/full/2026-10-15/title-16.xml?part=323) | 1 | normalized |
| `FTC_GREEN_GUIDES_GENERAL_ENVIRONMENTAL_BENEFIT_REFERENCE` | [eCFR Part 260](https://www.ecfr.gov/api/versioner/v1/full/2026-10-15/title-16.xml?part=260) | 1 | normalized |
| `FTC_COPPA_VERIFIABLE_PARENTAL_CONSENT_REFERENCE` | [eCFR Part 312](https://www.ecfr.gov/api/versioner/v1/full/2026-10-15/title-16.xml?part=312) | 1 | normalized |
| `ASA_CAP_3_1_REFERENCE` | [CAP Code rule 3.1](https://www.asa.org.uk/type/capcode/code_rule/3.1.html) | 1 | normalized |
| `ASA_CAP_3_7_SUBSTANTIATION_REFERENCE` | [CAP Code rule 3.7](https://www.asa.org.uk/type/capcode/code_rule/3.7.html) | 1 | normalized |
| `ASA_CAP_3_4_PRICE_INFORMATION_REFERENCE` | [CAP Code rule 3.4](https://www.asa.org.uk/type/capcode/code_rule/3.4.html) | 1 | normalized |

The Meta Transparency Center Prohibited Commercial Practices page was not retained as an excerpt source: its official fetch exposed only the page title, so no policy wording could be verified. The three Meta entries above are reference-only and do not establish a prohibition on false or misleading product claims. No Meta enforcement rule is active; Meta verification returns a typed human-review error rather than pretending a rule is enforced. The existing Google catalog and pack remain unchanged.

Run the integrity check with:

```sh
uv run python scripts/verify_policy_library.py
```
