# AdProof — how to hand this to Devin

Prepared October 17, 2026. This package contains a single integrated build specification, the three reference plans, and the existing local mock prototype. It does **not** contain a completed live app or any credentials.

## 1. What to give Devin

1. Open a Devin Cloud session connected to `Rathish-Rajendran/AdProof`.
2. Upload `ADPROOF_DEVIN_HANDOFF.zip` as a session attachment.
3. Paste the **entire contents** of `DEVIN_MASTER_PROMPT.md` as the task. Alternatively, upload the Markdown file and explicitly tell Devin to read it completely and treat it as authoritative.
4. Add the existing Gemini key and the new Sentry project's DSN through Devin's private Secrets feature, not in the task text or GitHub files.
5. Set a Devin spending/ACU limit appropriate to your remaining credit. Your $200 may belong to a particular service; do not assume Gemini, Devin, and hosting share one balance.

Suggested short message if attaching the master file rather than pasting it:

> Read DEVIN_MASTER_PROMPT.md completely and implement it as the authoritative whole-app specification. Inspect the attached ADPROOF_DEVIN_HANDOFF.zip first. Work in Rathish-Rajendran/AdProof, verify the actual base branch, and continue through its milestones without waiting for per-phase approval. Report missing private setup in one consolidated list while completing all independent code/tests. Never silently substitute mocks for live calls. Open a reviewable PR; do not auto-merge or make final hackathon submissions.

The ZIP includes the master prompt, this guide, the original plans, and a portable copy of the prototype. Devin Cloud cannot read your Mac's Downloads or Projects folders directly. If the interface does not accept the ZIP, attach the master Markdown and individual reference plans; the self-contained master brief is sufficient for the core build.

## 2. What you must provide privately

| Item | What you do | Put the value in the prompt? |
|---|---|---|
| Gemini API key | Add as `GEMINI_API_KEY` in Devin Secrets | No |
| Sentry project | Create a Python project, suggested name `adproof-backend` | No secret needed for the name |
| Sentry client DSN | Copy from the project's client/SDK settings; add as `SENTRY_DSN` | No |
| Stable agent identities | Let Devin generate three seeds securely once, then retain them in private storage for the judging runtime | No |
| Judging runtime | Choose your laptop or an existing authorized always-on host; keep all three agents running | Share only the nonsecret target choice |
| Real existing P3 code/identity, if it exists | Supply actual source and public agent address; seed privately only if needed | No private seed |

For the new Sentry project, confirm that **Tracing and Logs** are available and receiving events. The sponsor brief requires two products beyond error monitoring; those are the selected pair. A DSN alone does not prove either product is working. Do not buy a plan upgrade without deciding to do so yourself. [Sentry brief](https://docs.google.com/document/d/1JIlPd5vxcm8klztORkRX0FPXp4F865mxUbteJY8MUAw/edit)

You do **not** need to provide an ASI:One inference key just to use an ACP agent from ASI:One. An Agentverse management API key is not required for the baseline manually connected mailbox setup. Sentry's auth token is not needed for basic DSN ingestion. Devin already has repository access; no new GitHub token or Devin API key is required for this task. If Devin requests another credential, ask which concrete documented feature requires it.

Never send account passwords, browser cookies, two-factor codes, `.env` contents, or private seeds in the normal task prompt. If a key is accidentally committed, remove it from use and rotate it; merely deleting its visible line is not sufficient.

## 3. Human tasks that remain

You can divide these among the three people while Devin builds:

- **Person 1 — runtime and Fetch:** retain the private seeds, connect/claim the agents in Agentverse, keep the workers alive, and run the actual full ASI:One conversation. Save public agent profile links and safe conversation proof. Agentverse mailboxes route messages; they do not host the Python workers.
- **Person 2 — evidence and evaluation:** review the small official policy catalog and its applicability, check the AeroBeat facts/quotes/25% calculation, and review live evaluation failures. Do not mark placeholder rules ACTIVE to force a PASS.
- **Person 3 — demo and submission:** test the image/card experience in ASI:One, create the measured video, verify public links, prepare Devpost, and coordinate the Fetch Submission Agent team join process. Each teammate must join using the Team ID; the lead's registration alone is incomplete.

Also verify eligibility/admission and attend judging in person. Those requirements cannot be satisfied by generated code. [Event overview](https://la-ai-hackathon-2026.devpost.com/), [Fetch submission instructions](https://docs.google.com/document/d/1UDW-X1C24hxZviFOQzjTeh0pXRNAoflMb8lhJqZP9Z0/edit)

## 4. Important decisions already made

- **One integrated specification:** old plans have incompatible schemas, runtime versions, decisions, and nested workflows. The master resolves them instead of concatenating instructions.
- **Electronics demo:** Google Ads / US / English / explicit adult audience, with AeroBeat AB-01 synthetic product facts. No health-category launch scope.
- **Evidence first:** $80 down to $60 is 25% off; up to 30-hour ANC-off battery; splash-resistant, not waterproof; no athlete endorsement proof.
- **Honest outcomes:** the main repairable example is FIX_REQUIRED → PASS, not an invented BLOCK. A wrong price embedded in an unchanged image stays unresolved after copy repair.
- **One orchestrator:** local image-inspector module, real verifier agent, real remediator agent, then independent re-audit. Remediation never declares its own rewrite safe.
- **Real sponsor use:** ACP/Agentverse/ASI:One and genuine specialist transport; live Gemini image/text inference; Sentry Tracing + Logs with a demonstrated improvement; actual Devin build provenance.
- **No extra sponsor tools:** avoid expanding the stack before the complete working flow.
- **No guaranteed wins:** the brief targets a coherent, testable, eligible demonstration; judging and prize outcomes are outside anyone's control.

## 5. Repository and artifact caveats

At the research check, GitHub reported the repository public, empty, and configured with lowercase **`main`**, not `Main`. The prompt tells Devin to recheck and bootstrap only if it is still empty. It must preserve any code added in the meantime. No remote repository changes were made while preparing this package.

The bundled prototype is the previously built **MOCK-only** demo. It has real local workflow coordination around deterministic fixtures, not Fetch/Gemini/Sentry integration. Its older synthetic health/BLOCK scenarios are historical examples, not the new electronics policy rules. The mock README contains a laptop-specific launch path; from the portable `mock-demo` folder the equivalent is `python3 -m adproof --port 8765`. Its offline tests run with `python3 -m unittest discover -s tests -v`.

The Person 3 plan says live code, a registration, and tests already exist, but those files were not present in the supplied empty remote repository or local mock demo. If your teammate has that code in another checkout, give it to Devin. Do not give out a private seed publicly or replace a working registered identity accidentally.

`MANIFEST.json` records SHA-256 hashes of the packaged inputs. The archive uses an explicit source-file allowlist, excluding environments, caches, `.git`, runtime state, identity files, and credentials. Still review any additional files before uploading them.

## 6. What completion should look like

Ask Devin for one PR and its `docs/validation-status.md`, not merely a screenshot or a claim that everything is done. It must distinguish offline tests, real model tests, real agent transport, Agentverse registration, ASI:One end-to-end proof, Sentry ingestion, and durable runtime status.

The current event overview lists **October 18, 2026, noon PDT** as the deadline. Plan to freeze features at 08:00, record by 09:30, and submit by 11:00 if still feasible. Confirm any contradictory rule text with onsite organizers. [Official event page](https://la-ai-hackathon-2026.devpost.com/)

Do not accept “live complete” if the app only passes mocked tests, if the agent workers die when the Devin session closes, if policy coverage is fabricated, or if a copy-only rewrite claims to have changed image pixels.
