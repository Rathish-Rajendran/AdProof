"""Actual application control around deterministic, replaceable mock specialists."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import re
import threading
import time
import uuid

from .errors import DemoError
from .fixtures import get_scenario
from . import specialists


DECISIONS = {"PASS", "FIX_REQUIRED", "BLOCK", "HUMAN_REVIEW"}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def validate_result(operation, result):
    """Validate the demo's boundary before trusting a specialist response."""
    if not isinstance(result, dict):
        raise DemoError("INVALID_SPECIALIST_RESPONSE", "Specialist result must be an object.")
    list_fields = {
        "INSPECT": ("visible_text", "visual_assertions", "atomic_claims", "inspection_warnings"),
        "VERIFY": ("claims", "issues", "retrieval_warnings", "source_snapshots"),
        "REPAIR": ("changes", "unresolved_issue_ids"),
    }[operation]
    if any(not isinstance(result.get(key), list) for key in list_fields):
        raise DemoError("INVALID_SPECIALIST_RESPONSE", "Specialist result is missing required list fields.")
    if operation == "INSPECT":
        if not isinstance(result.get("image_sha256"), str):
            raise DemoError("INVALID_SPECIALIST_RESPONSE", "Inspection must identify the frozen image.")
    if operation == "VERIFY":
        if result.get("decision") not in DECISIONS:
            raise DemoError("INVALID_SPECIALIST_RESPONSE", "Verification returned an invalid decision.")
        for issue in result["issues"]:
            if not isinstance(issue, dict) or any(key not in issue for key in ("issue_id", "severity", "source", "auto_fixable")):
                raise DemoError("INVALID_SPECIALIST_RESPONSE", "Verification returned an invalid issue.")
        if any(issue["severity"] == "CRITICAL" for issue in result["issues"]) and result["decision"] != "BLOCK":
            raise DemoError("INVALID_SPECIALIST_RESPONSE", "A critical finding cannot be presented as a cleared campaign.")
    if operation == "REPAIR":
        if not isinstance(result.get("repaired_copy"), str) or not 1 <= len(result["repaired_copy"].strip()) <= 2000 or "decision" in result:
            raise DemoError("INVALID_SPECIALIST_RESPONSE", "Repair must supply copy without assigning a decision.")
    return result


def validate_campaign(campaign):
    if not isinstance(campaign, dict):
        raise DemoError("INVALID_INPUT", "Campaign must be a JSON object.")
    result = deepcopy(campaign)
    creative, context = result.get("creative"), result.get("campaign")
    if not isinstance(creative, dict) or not isinstance(context, dict):
        raise DemoError("INVALID_INPUT", "Provide creative and campaign context objects.")
    copy = creative.get("ad_copy")
    if not isinstance(copy, str) or not copy.strip() or len(copy) > 2000:
        raise DemoError("INVALID_INPUT", "Ad copy must contain 1–2,000 characters.", fields=["creative.ad_copy"])
    if creative.get("image_url") not in {"/static/creatives/neutral.svg", "/static/creatives/unsafe.svg"}:
        raise DemoError("INVALID_INPUT", "This offline demo accepts its neutral or unsafe fixture image only.")
    if result.get("landing_page_url") != "fixture://acme-balance":
        raise DemoError("INVALID_INPUT", "This offline demo uses fixture://acme-balance. No external URLs are fetched.")
    if creative.get("format") != "IMAGE" or result.get("schema_version") != "1.0":
        raise DemoError("INVALID_INPUT", "Use schema_version 1.0 and creative format IMAGE.")
    if any(context.get(key) != expected for key, expected in {
        "platform": "GOOGLE_ADS", "jurisdiction": "US", "category": "HEALTH_WELLNESS"
    }.items()):
        raise DemoError("UNSUPPORTED_CONTEXT", "The demo supports Google Ads, United States, and health/wellness.")
    if result.get("evidence_documents", []) != []:
        raise DemoError("UNSUPPORTED_CONTEXT", "Additional evidence documents are not enabled in this offline demo.")
    creative["ad_copy"] = copy.strip()
    return result


@dataclass
class _Audit:
    audit_id: str
    owner: str
    request_id: str
    campaign: dict
    scenario: dict
    fingerprint: str
    created_at: str = field(default_factory=utc_now)
    started: float = field(default_factory=time.monotonic)
    state: str = "RECEIVED"
    workflow_status: str = "RUNNING"
    events: list = field(default_factory=list)
    messages: list = field(default_factory=list)
    report: dict | None = None
    done: threading.Event = field(default_factory=threading.Event)


class MockGateway:
    """A labeled local transport seam. It does not connect to sponsor services."""

    def __init__(self, manager, audit):
        self.manager, self.audit = manager, audit
        self.task_results = {}

    async def call(self, operation, payload, *, phase, stage, role):
        task_id = f"{self.audit.audit_id}:{operation}:{phase}"
        if task_id in self.task_results:
            return deepcopy(self.task_results[task_id])
        for attempt in (1, 2):
            message = {
                "schema_version": "1.0", "request_id": self.audit.request_id,
                "audit_id": self.audit.audit_id, "task_id": task_id,
                "candidate_id": payload.get("candidate_id", f"{self.audit.audit_id}:{phase}"),
                "operation": operation, "phase": phase, "attempt": attempt,
                "execution_mode": "MOCK", "sender": "orchestrator", "recipient": role,
                "direction": "request", "timestamp": utc_now(), "payload": deepcopy(payload),
            }
            self.manager._message(self.audit, message)
            self.manager._event(self.audit, "message_sent", stage, role, phase,
                                f"Dispatched {operation.lower()} · attempt {attempt}", {"task_id": task_id, "attempt": attempt})
            await asyncio.sleep(self.manager.step_delay)
            try:
                behavior = self.audit.scenario["behavior"]
                should_timeout = operation == "VERIFY" and (
                    (behavior == "verifier_timeout" and phase == "ORIGINAL")
                    or (behavior == "reverification_timeout" and phase == "REPAIRED")
                    or (behavior == "transient_retry" and phase == "ORIGINAL" and attempt == 1)
                )
                if should_timeout:
                    raise TimeoutError("Synthetic verifier response deadline exceeded.")
                if operation == "INSPECT":
                    result = await specialists.inspect_creative(payload["campaign"], phase=phase)
                elif operation == "VERIFY":
                    result = await specialists.verify_campaign(payload)
                elif operation == "REPAIR":
                    result = await specialists.repair_copy(payload)
                else:
                    raise DemoError("INVALID_OPERATION", "Unknown specialist operation.")
                validate_result(operation, result)
                if operation == "VERIFY" and (result.get("candidate_id") != payload["candidate_id"] or result.get("phase") != phase):
                    raise DemoError("INVALID_SPECIALIST_RESPONSE", "Verification reply belongs to a different candidate.")
                response = dict(message, sender=role, recipient="orchestrator", direction="response", timestamp=utc_now(), payload=result, ok=True)
                self.manager._message(self.audit, response)
                self.manager._event(self.audit, "message_received", stage, role, phase,
                                    f"Validated {operation.lower()} result", {"task_id": task_id, "attempt": attempt})
                self.task_results[task_id] = deepcopy(result)
                return result
            except TimeoutError:
                response = dict(message, sender=role, recipient="orchestrator", direction="response", timestamp=utc_now(),
                                ok=False, payload=None, error={"code": "SPECIALIST_TIMEOUT", "message": "Simulated verifier timeout."})
                self.manager._message(self.audit, response)
                if attempt == 1:
                    self.manager._event(self.audit, "retry", stage, role, phase,
                                        "Response deadline exceeded. Retrying once with the same task ID.", {"attempt": 2, "task_id": task_id})
                    await asyncio.sleep(self.manager.step_delay / 2)
                else:
                    raise DemoError("SPECIALIST_TIMEOUT", "The simulated verifier did not respond after two attempts.", 504) from None


class AuditManager:
    def __init__(self, step_delay=0.55, max_active=2):
        self.step_delay = max(0, float(step_delay))
        self.max_active = max_active
        self._lock = threading.RLock()
        self._audits = {}
        self._requests = {}
        self._pool = ThreadPoolExecutor(max_workers=max_active, thread_name_prefix="adproof")
        self._closed = False

    def submit(self, scenario_id, campaign=None, request_id=None, owner="test-owner"):
        scenario = get_scenario(scenario_id)
        campaign = validate_campaign(campaign if campaign is not None else scenario["campaign"])
        request_id = request_id or campaign.get("request_id") or f"request_{uuid.uuid4().hex[:12]}"
        if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", request_id):
            raise DemoError("INVALID_INPUT", "Request ID must be 1–80 letters, numbers, hyphens, or underscores.")
        campaign["request_id"] = request_id
        fingerprint = hashlib.sha256(json.dumps({"campaign": campaign, "scenario": scenario_id}, sort_keys=True).encode()).hexdigest()
        with self._lock:
            if self._closed:
                raise DemoError("SHUTTING_DOWN", "The demo is shutting down.", 503)
            existing = self._requests.get((owner, request_id))
            if existing:
                audit = self._audits[existing]
                if audit.fingerprint != fingerprint:
                    raise DemoError("DUPLICATE_REQUEST_CONFLICT", "This request ID belongs to different input. Start a new audit.", 409)
                self._event(audit, "replay", audit.state, "orchestrator", "ORIGINAL", "Duplicate request reused the existing audit; no specialist call was repeated.")
                return self._snapshot(audit), True
            if sum(not audit.done.is_set() for audit in self._audits.values()) >= self.max_active:
                raise DemoError("BUSY", "Two audits are already running. Wait a moment and try again.", 429)
            # This is an in-memory local demo; bound completed records for long sessions.
            if len(self._audits) >= 100:
                old = next((a for a in self._audits.values() if a.done.is_set()), None)
                if old:
                    self._audits.pop(old.audit_id)
                    self._requests.pop((old.owner, old.request_id), None)
            audit_id = f"audit_{uuid.uuid4().hex[:12]}"
            audit = _Audit(audit_id, owner, request_id, campaign, scenario, fingerprint)
            self._audits[audit_id] = audit
            self._requests[(owner, request_id)] = audit_id
            self._event(audit, "stage_started", "RECEIVED", "orchestrator", "ORIGINAL", "Campaign accepted. Execution mode: MOCK.")
            self._pool.submit(self._execute, audit)
            return self._snapshot(audit), False

    def _authorized(self, audit_id, owner):
        audit = self._audits.get(audit_id)
        if audit is None or audit.owner != owner:
            raise DemoError("NOT_FOUND", "Audit not found in this browser session.", 404)
        return audit

    def get(self, audit_id, owner="test-owner"):
        with self._lock:
            return self._snapshot(self._authorized(audit_id, owner))

    def wait(self, audit_id, owner="test-owner", timeout=5.0):
        with self._lock:
            audit = self._authorized(audit_id, owner)
        if not audit.done.wait(timeout):
            raise DemoError("WAIT_TIMEOUT", "Audit is still running.", 504)
        return self.get(audit_id, owner)

    def _snapshot(self, audit):
        return deepcopy({
            "audit_id": audit.audit_id, "request_id": audit.request_id,
            "scenario_id": audit.scenario["id"], "state": audit.state,
            "execution_mode": "MOCK", "workflow_status": audit.workflow_status,
            "created_at": audit.created_at, "events": audit.events,
            "report": audit.report,
            "messages": audit.messages,
            "elapsed_ms": round((time.monotonic() - audit.started) * 1000) if not audit.report else audit.report["timings_ms"]["total"],
        })

    def _event(self, audit, kind, stage, agent, phase, message, data=None):
        with self._lock:
            audit.events.append({
                "seq": len(audit.events) + 1, "type": kind, "stage": stage,
                "agent": agent, "phase": phase, "message": message,
                "elapsed_ms": round((time.monotonic() - audit.started) * 1000),
                "data": deepcopy(data or {}),
            })

    def _message(self, audit, message):
        with self._lock:
            audit.messages.append(deepcopy(message))

    def _stage(self, audit, state, role, phase, description):
        with self._lock:
            audit.state = state
        self._event(audit, "stage_started", state, role, phase, description)

    def _execute(self, audit):
        try:
            asyncio.run(self._run(audit))
        finally:
            audit.done.set()

    async def _run(self, audit):
        gateway = MockGateway(self, audit)
        original, repaired, repair, inspection = None, None, None, None
        errors, timings = [], {}
        phase = "ORIGINAL"
        original_id = f"{audit.audit_id}:original"
        repaired_id = f"{audit.audit_id}:repaired"

        async def call(operation, payload, state, role, current_phase, description):
            self._stage(audit, state, role, current_phase, description)
            start = time.monotonic()
            try:
                result = await gateway.call(operation, payload, phase=current_phase, stage=state, role=role)
            finally:
                timings[state.lower()] = round((time.monotonic() - start) * 1000)
            self._event(audit, "stage_completed", state, role, current_phase, description + " Complete.")
            return result

        try:
            self._stage(audit, "VALIDATING", "orchestrator", phase, "Validated campaign context and assigned correlation IDs.")
            inspection = await call("INSPECT", {"campaign": audit.campaign, "candidate_id": original_id}, "INSPECTING_ORIGINAL", "inspector", phase, "Inspecting original copy and frozen fixture image.")
            original = await call("VERIFY", {"candidate_id": original_id, "phase": phase, "campaign": audit.campaign, "inspection": inspection}, "VERIFYING_ORIGINAL", "verifier", phase, "Checking claims against bundled evidence.")
            self._event(audit, "decision", audit.state, "verifier", phase, f"Original decision: {original['decision']}", {"decision": original["decision"], "claims": len(original["claims"]), "issues": len(original["issues"])})
            if original["decision"] != "PASS" and any(issue["auto_fixable"] for issue in original["issues"]):
                repair = await call("REPAIR", {"candidate_id": original_id, "campaign": audit.campaign, "verification": original}, "REPAIRING_COPY", "remediator", phase, "Drafting the minimum factual copy repair.")
                candidate = deepcopy(audit.campaign)
                candidate["creative"]["ad_copy"] = repair["repaired_copy"]
                phase = "REPAIRED"
                reinspected = await call("INSPECT", {"campaign": candidate, "candidate_id": repaired_id}, "INSPECTING_REPAIRED", "inspector", phase, "Inspecting new copy with the unchanged image.")
                if reinspected["image_sha256"] != inspection["image_sha256"]:
                    raise DemoError("IMAGE_SNAPSHOT_MISMATCH", "The creative image changed during re-audit.")
                repaired = await call("VERIFY", {"candidate_id": repaired_id, "phase": phase, "campaign": candidate, "inspection": reinspected}, "VERIFYING_REPAIRED", "verifier", phase, "Independently verifying the revised candidate.")
                self._event(audit, "decision", audit.state, "verifier", phase, f"Re-audit decision: {repaired['decision']}", {"decision": repaired["decision"], "claims": len(repaired["claims"]), "issues": len(repaired["issues"])})
        except DemoError as error:
            errors.append({"code": error.code, "stage": audit.state, "message": error.message, "retryable": error.code == "SPECIALIST_TIMEOUT"})
            self._event(audit, "error", audit.state, "orchestrator", phase, error.message, {"code": error.code})
        except Exception:
            errors.append({"code": "INTERNAL_ERROR", "stage": audit.state, "message": "Unexpected demo error; no unverified candidate was approved.", "retryable": False})
            self._event(audit, "error", audit.state, "orchestrator", phase, errors[-1]["message"], {"code": "INTERNAL_ERROR"})

        final = repaired["decision"] if repaired else (original["decision"] if original else "HUMAN_REVIEW")
        status = "COMPLETED" if not errors else "PARTIAL"
        reasons = []
        if errors:
            reasons.append("A required stage could not finish. No unverified repair was approved.")
        if repaired and any(issue["source"] != "AD_COPY" for issue in repaired["issues"]):
            reasons.append("Claims remain in the original image. Replace that image and submit a new campaign.")
        if not original:
            reasons.append("No original verification result is available. A human must review the campaign.")
        timings["total"] = round((time.monotonic() - audit.started) * 1000)
        report = {
            "schema_version": "1.0", "request_id": audit.request_id, "audit_id": audit.audit_id,
            "execution_mode": "MOCK", "workflow_status": status,
            "initial_decision": original["decision"] if original else None,
            "claims": original["claims"] if original else [], "issues": original["issues"] if original else [],
            "repair": repair, "repaired_decision": repaired["decision"] if repaired else None,
            "final_decision": final, "final_candidate_id": repaired_id if repaired else original_id,
            "repaired_verification": repaired, "human_review_reasons": reasons, "errors": errors,
            "provenance": {"policy_pack_version": "synthetic-demo-v1", "model_outputs_are_advisory": True,
                           "image_sha256": inspection["image_sha256"] if inspection else None,
                           "image_hash_kind": "synthetic fixture identity, not downloaded bytes",
                           "evidence_source": "bundled synthetic fixture", "live_services_called": [],
                           "campaign_context": deepcopy(audit.campaign["campaign"])},
            "timings_ms": timings, "messages": deepcopy(audit.messages),
        }
        with self._lock:
            audit.state = "COMPLETED" if not errors else "PARTIAL"
            audit.workflow_status = status
            audit.report = report
            self._event(audit, "complete", audit.state, "orchestrator", phase,
                        f"Audit finished: {final}. All specialist output is synthetic.", {"decision": final, "workflow_status": status})

    def close(self):
        with self._lock:
            self._closed = True
        self._pool.shutdown(wait=True)
