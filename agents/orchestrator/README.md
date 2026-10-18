# AdProof Orchestrator

AdProof performs a bounded preflight of AI-generated advertising for the implemented Google Ads / US / English / adult-targeted consumer-electronics scope. It extracts objective claims, checks them against supplied source evidence and reviewed policy predicates, and can propose one minimal copy-only repair followed by a fresh audit. The image is frozen and unchanged during repair.

Send `help` for supported plain-text commands:

- `example`
- `demo aerobeat` for the unsafe-copy case with one repair, `demo aerobeat49` for the image-price mismatch, or `demo aerobeat correct` for the supported copy audit
- `status <audit_id>` or `report <audit_id>` within the same owner/session
- A fenced `CampaignInput` JSON object, or `Image:`, `Copy:`, and `Page:` fields

Each audit is bounded by the configurable workflow deadline (600 seconds by default), a model-call budget, a maximum of one repair, and a per-owner concurrency limit. LIVE execution uses Ollama by default (`OLLAMA_MODEL=qwen2.5vl:3b`) or Gemini when `ADPROOF_MODEL_PROVIDER=gemini` and `GEMINI_API_KEY` are configured; it never silently falls back to fixtures. Reports are bounded evidence summaries, not legal advice, legal review, platform certification, or a safety guarantee. Human review is required outside the implemented scope and when evidence or model availability is incomplete.

Agent address: `runtime/agents.json` on the configured runtime volume.
