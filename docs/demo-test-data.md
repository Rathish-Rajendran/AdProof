# Demo test data

Upload [the non-compliant demo image](images/demo-noncompliant-ad.png), copied from `/home/ubuntu/plans/adproof_test_ad.png`.

Send these exact inputs to the orchestrator in ASI:One:

| Input | Expected result |
|---|---|
| Upload `docs/images/demo-noncompliant-ad.png` | Needs review; any `fixed_text` is only a suggestion. |
| `check AeroBeat AB-01 headphones are 100% waterproof with 48-hour battery life. Rated #1 by 1,000 athletes. Only $49 - 50% off!` | Fixed once, re-checked, and ready. |
| `check AeroBeat AB-01 headphones are splash-resistant with up to 30 hours of battery life with ANC off. Now $60, 25% off the regular $80.` | Ready without a fix. |
| `generate a Google Ads ad for AeroBeat AB-01 headphones for US adults` | Ready. |
| `generate a Google Ads ad for AeroBeat AB-02 Pro earbuds for teens` | Needs review. |
| `generate a Meta ad for the AeroBeat Mini speaker for US adults` | Needs review; Meta rules are not active. |

For every message, either select the agent in the **To:** box or start the message with `@<orchestrator address>`. Otherwise, ASI:One sends it to its own AI.
