# Devin prompt: AdProof, Person 3 (Inspector, Repair, Interactive Cards)

> **Before you paste this into Devin:**
> 1. Push the current `adproof` folder to GitHub and give Devin access to that repo.
> 2. Add these as **Devin secrets** (never paste keys into the prompt): `VISION_API_KEY` (Gemini), `ASI_ONE_API_KEY`, `AGENTVERSE_API_KEY`.
> 3. Paste everything below the line. Then tell Devin "Start Phase 0" and review each PR before saying "Next phase".

---

## 1. Context

You are the engineer for **Person 3** on a 3-person team at the **LA Hacks AI Hackathon, Fetch.ai track**.
- **Hard deadline:** submissions close **Sunday Oct 18, 2026, 12:00 PDT**. All code must be merged by **Sunday 06:00 PDT**; after that only bug fixes.
- **Judging:** functionality 25%, use of Fetch.ai tech 20%, innovation 20%, real-world impact 20%, UX and presentation 15%. Bonus points for multi-agent collaboration, Interactive Cards, reliability and error recovery, and real-time data.
- **Mandatory Fetch.ai rules:** agent registered on Agentverse, implements the Agent Chat Protocol, discoverable and usable in ASI:One, whole user flow inside an ASI:One conversation (no custom frontend), public GitHub repo with run instructions.

**Product: AdProof.** An advertiser sends an ad (copy, image, landing page URL, platform) to our agent in ASI:One. AdProof:
1. splits the copy into claims and checks each against the landing page (Person 2),
2. reads the ad **image** and compares it with the copy and the landing page (**you**),
3. returns `PASS | FIX_REQUIRED | BLOCK | HUMAN_REVIEW` with evidence for every finding,
4. **repairs** the ad with the smallest safe edits (**you**),
5. **re-audits** the repaired ad and shows before → after (**you**).

AdProof is a risk and repair assistant. Never claim legal certification or guaranteed compliance anywhere in code, cards or docs.

**Team split**
- **Person 1:** orchestrator uAgent, Agentverse, Chat Protocol, Payment Protocol. Owns `orchestrator/` and `shared/`.
- **Person 2:** landing-page extraction, claim verification, policy rules, evaluation set.
- **Person 3 (you):** `agents/inspector/`, `agents/remediation/`, `cards/`, `tests/test_person3.py`, `README_PERSON3.md`, `CONTRACT_PROPOSAL_PERSON3.md`, `requirements-person3.txt`, `.env.example`.

## 2. Docs you must use (read before writing Fetch.ai code)

Do not guess Fetch.ai APIs from memory. Read these and the installed source (`uagents`, `uagents_core`) first:
- Interactive Cards: https://innovationlab.fetch.ai/resources/docs/interactive-cards/asi-interactive-cards
- Card playground: https://asi1.ai/developer/card-playground
- Agent Chat Protocol: https://innovationlab.fetch.ai/resources/docs/agent-communication/agent-chat-protocol
- uAgents creation and mailbox agents: https://innovationlab.fetch.ai/resources/docs/agent-creation/uagent-creation
- Agent-to-agent messages: https://innovationlab.fetch.ai/resources/docs/agent-communication/uagent-uagent-communication
- ASI:One API (OpenAI-compatible, `https://api.asi1.ai/v1`, models `asi1`, `asi1-mini`): https://innovationlab.fetch.ai/resources/docs/asione/asi-one-quickstart
- Example agents, including image and resource handling: https://github.com/fetchai/innovation-lab-examples

## 3. The existing code (it already works; build on it)

**Do not rewrite or restructure it.** Read `README_PERSON3.md` and `CONTRACT_PROPOSAL_PERSON3.md` first.

What exists:
- `agents/inspector/inspector.py`: extraction (vision model via any OpenAI-compatible endpoint, or offline from a fixture's `creative_spec`) + **deterministic** comparison producing `visual_findings.contradictions` of types `discount_mismatch, price_mismatch, unverified_visual_endorsement, implied_results_imagery, missing_ai_disclosure, visual_only_claim`. The model only reads; code decides.
- `agents/remediation/repair.py`: minimal copy edits per issue category, image edit instructions, re-rendered creative for spec-based fixtures, optional ASI:One polish kept only if it audits no worse.
- `agents/remediation/pipeline.py`: `audit(ad, landing)` and `run(ad, landing)` (audit → repair → re-audit, max 2 rounds). `VERIFY = verify_copy` is a **mock of Person 2** (`agents/remediation/mocks/mock_verifier.py`).
- `agents/inspector/mocks/mock_landing_extract.json`: **mock of Person 2's** landing-page extraction.
- `cards/builders.py`: 5 cards (intake form, verdict + ledger, evidence detail, repair review, before/after) + `validate()`.
- `cards/selection.py`: parses card clicks (JSON for direct @mention, prose when planner-routed).
- `cards/demo_agent.py`: mailbox uAgent that runs the whole flow. It is **registered and live on Agentverse** (Active, ASI Available). Chat commands: `demo`, `demo clean`, `demo blurry`.
- Fixtures: `fake_ad` (risky → BLOCK → PASS after repair), `safe_ad` (PASS, no changes), `unclear_ad` (blurred → HUMAN_REVIEW).

## 4. Hard rules

1. **Only edit Person 3 files** (list in section 1). Never edit `orchestrator/` or `shared/`. Shared schema changes go into `CONTRACT_PROPOSAL_PERSON3.md` as a proposal.
2. **No secrets in git.** Read keys from env via `python-dotenv`. New variables go into `.env.example` with empty values. Add any cache or download folders to `.gitignore`.
3. **Never change `P3_AGENT_SEED` handling or the agent name** in `demo_agent.py`. That would change the live agent's address and break its registration.
4. **Keep all 10 existing tests passing.** Every phase adds tests. **Tests must run offline with no keys**: mock all HTTP and model calls.
5. **Never fabricate.** If a model call fails, fall back and label it (`extraction_mode`). If the image can't be read, return `HUMAN_REVIEW`. If a comparison or download fails, say so in chat.
6. **Decisions stay deterministic.** Models extract or rephrase; code decides PASS/BLOCK. Any model-written text is re-audited before it is shown.
7. **Python 3.14** must work (the team laptop runs it). Keep the explicit `asyncio.new_event_loop()` + `Agent(loop=...)` pattern.
8. Branch `person3/devin`. **One PR per phase.** Keep diffs focused.
9. **Do not upgrade** `uagents` / `uagents-core` major versions. Pin anything you add.

## 5. ASI:One Interactive Cards: rules

- A card = one `TextContent` + one `MetadataContent` in a `ChatMessage`. Keys: `card_protocol_version: "1"`, `requires_card_interaction: "true"`, `card_kind` (`carousel|detail|form|review|custom`), `card_payload` (JSON string). Optional: `is_terminal`, `preferred_drawer_width_px`.
- All metadata values are **strings**. Payload at top level, no envelope. ≤ 64 KB. Custom tree ≤ 8 levels. Badge variants only `info | success | warning`.
- Invalid cards are silently dropped to plain text, so the `TextContent` must always make sense alone.
- Clicks return as JSON (direct @mention) **or** prose (planner-routed). Always go through `cards/selection.py`.
- Images need **public URLs**; base64 won't fit in 64 KB.
- Always build metadata with `builders.card_metadata()` (it validates).

## 6. How to test without ASI:One

You can't click in ASI:One, so test the agent handler directly: build `ChatMessage` objects and call `on_message(ctx, sender, msg)` with a fake `ctx` that has `send()` (collects messages), `storage.get/set`, and `logger`. Assert on the returned `TextContent` and card metadata. Add this harness as `tests/helpers_p3.py` and reuse it in every phase. At the end of each phase, list the exact chat messages a human should type in ASI:One to verify it live.

## 7. Tasks, in priority order (one PR each)

If time runs short, finish phases in this order and stop: **0 → 1 → 2 → 4 → 3 → 5 → 6.**

### Phase 0: Baseline (≈15 min)
Set up, run `python -m pytest -q tests/test_person3.py` (expect 10 passed), run `python -m agents.remediation.pipeline risky|clean|unclear`, add the test harness from section 6. PR: harness + nothing else.

### Phase 1: Real image reading with Gemini (≈1.5 h)
- Gemini via its OpenAI-compatible endpoint, already supported by `extract_with_vision()`: `VISION_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai`. **Confirm the current Flash model name by calling the models list endpoint**; don't hard-code from memory. Put it in `VISION_MODEL`.
- If `response_format: json_object` is rejected, fall back to asking for JSON in the prompt and parsing the first JSON object from the reply.
- Prompt returns strict JSON including `legible` (bool). Validate the shape; retry once on malformed output; then fall back to offline mode or `HUMAN_REVIEW`.
- 30 s timeout, 1 retry, on-disk cache keyed by image SHA-256 (gitignored folder).
- When a key is set, pixels win over `creative_spec`.
- Show the source in the verdict card subtitle: "Image read by Gemini" or "Image read from sample description".
- **Done when:** with a key, `inspect()` on `fake_ad.png` returns `extraction_mode` starting `vision:` and finds at least `discount_mismatch`, `price_mismatch`, `unverified_visual_endorsement`; `unclear_ad.png` gives `HUMAN_REVIEW`; offline tests mock the HTTP call. Report the real Gemini output for all three fixtures in the PR.

### Phase 2: Advertiser attaches a real ad in ASI:One (≈2 h)
- ASI:One attachments arrive as `ResourceContent(resource_id, resource=Resource(uri, metadata))`. Download them with `uagents_core.storage.ExternalStorage(...).download(resource_id)` using `AGENTVERSE_API_KEY`. Follow the image-handling example in `fetchai/innovation-lab-examples`. **Log the raw incoming content types the first time** so we can see the real shape, and handle both a single resource and a list.
- Also accept a plain image URL in the text: http(s) only, block private/localhost addresses, ≤ 8 MB, image MIME types only.
- Accept free-text submissions: copy + landing URL in one message builds the `ad` dict without the form.
- Landing data stays Person 2's job: pass `{"url": url}` and keep the `TODO`. Claims will show "No evidence" until then; the card must say that clearly rather than look broken.
- **Done when:** simulated `ResourceContent` and image-URL messages each produce a verdict card (downloads stubbed in tests).

### Phase 4: Images inside the cards (≈1 h)
- Save repaired images with unique names per run (`<ad_id>_<hash>_repaired.png`).
- Preferred: upload original and repaired images with `ExternalStorage` and use the returned public URL if one is available (check `create_asset` / `set_permissions` in the installed `uagents_core.storage`). Fallback: `ADPROOF_IMAGE_BASE_URL` (raw GitHub URL of the fixtures folder).
- Show the ad in the verdict card and both ads side by side in the final card; omit cleanly when no URL is available.

### Phase 3: Inspector + Repair as a separate agent (≈2 h, multi-agent bonus)
- New file `agents/remediation/p3_agent.py`: mailbox uAgent `adproof_inspector_repair`, seed from a **new** variable `P3_WORKER_SEED`.
- Messages as uAgents `Model` classes: `InspectRequest(ad_json: str, landing_json: str)` → `InspectResponse(visual_findings_json: str)`, and `RepairRequest(ad_json, landing_json, issues_json)` → `RepairResponse(repair_json, final_audit_json)`. Use JSON strings to keep schemas simple.
- **Important:** uAgents matches messages by schema digest, so Person 1 must import these exact classes. Put them in one file `agents/remediation/p3_messages.py` with no other imports from our code, and document the import line in `CONTRACT_PROPOSAL_PERSON3.md`.
- `cards/demo_agent.py` stays unchanged as the standalone demo and fallback.
- **Done when:** a local test agent sends `InspectRequest` and gets a valid `InspectResponse`.

### Phase 5: "Generic AI vs AdProof" comparison (≈1 h)
- Verdict card button "Compare with a generic AI". Send only the ad copy to ASI:One `asi1-mini`: "Is this ad safe to run? List any problems." Show the reply next to AdProof's result in a `detail` card.
- Be honest: show what the generic AI flagged vs what AdProof flagged, and list the AdProof findings that needed the landing page or the image (price/discount mismatches, false urgency, image-only problems). Never claim the generic AI said "looks fine" unless it did.
- Cache per ad. If the key is missing or the call fails, show "Comparison unavailable".

### Phase 6: Discovery, docs, polish (≈1 h)
- Rewrite `cards/AGENT_README.md` so ASI:One routes the right users to us: plain-language description plus the phrases advertisers would type ("check my ad before launch", "is this ad compliant", "verify ad claims"). Include the agent name and address and these badges:
  `![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)` `![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)`
- Update `README_PERSON3.md`: what's real vs mocked, every env var, how to run both agents, how Person 1 and 2 plug in.
- Chat error messages are one sentence and say what to do next.

## 8. What to deliver at the end of every phase

1. A PR on `person3/devin` with a description: what changed, how you tested it, what is still mocked.
2. Full test output (`python -m pytest -q`).
3. The exact messages to type in ASI:One to verify the phase live.
4. Any decision you made that the team should know about, in 3 lines or fewer.

## 9. Stop and ask before

- changing the shared JSON contract or anything in `shared/`,
- anything touching agent seeds, names or Agentverse registration,
- deleting existing code or tests,
- adding a paid service or a new heavy dependency.
