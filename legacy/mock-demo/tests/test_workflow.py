"""Behavior tests for the local, deliberately mocked orchestration demo.

Run with: python3 -m unittest discover -s tests -v
The tests use the public AuditManager interface so they also act as examples
for callers integrating the eventual real specialists.
"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import unittest
from unittest.mock import patch

from adproof import specialists
from adproof.errors import DemoError
from adproof.fixtures import get_scenario, list_scenarios
from adproof.workflow import AuditManager


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.manager = AuditManager(step_delay=0.0)
        self.owner = "test-owner"

    def tearDown(self):
        self.manager.close()

    def run_scenario(self, scenario_id):
        snapshot, replayed = self.manager.submit(scenario_id, owner=self.owner)
        self.assertFalse(replayed)
        final = self.manager.wait(snapshot["audit_id"], self.owner, timeout=5.0)
        self.assertIsNotNone(final["report"], final)
        self.assertEqual(final["report"]["execution_mode"], "MOCK")
        return final

    def assert_error_code(self, action, expected_status):
        with self.assertRaises(DemoError) as raised:
            action()
        self.assertEqual(raised.exception.status, expected_status)

    def test_fixture_catalog_exposes_all_demo_scenarios(self):
        scenarios = list_scenarios()
        self.assertTrue(all(isinstance(item, dict) for item in scenarios))
        ids = {item["id"] for item in scenarios}
        self.assertTrue({
            "copy_repair", "unsafe_image", "safe_campaign",
            "verifier_timeout", "reverification_timeout", "transient_retry",
        }.issubset(ids))
        for scenario_id in ids:
            self.assertIsInstance(get_scenario(scenario_id), dict)

    def test_supported_copy_repair_is_independently_reverified(self):
        result = self.run_scenario("copy_repair")
        report = result["report"]
        self.assertEqual(report["initial_decision"], "BLOCK")
        self.assertEqual(report["repaired_decision"], "PASS")
        self.assertEqual(report["final_decision"], "PASS")
        self.assertTrue(report["repair"])

    def test_unrepaired_image_claim_keeps_campaign_blocked(self):
        result = self.run_scenario("unsafe_image")
        report = result["report"]
        self.assertEqual(report["initial_decision"], "BLOCK")
        self.assertEqual(report["repaired_decision"], "BLOCK")
        self.assertEqual(report["final_decision"], "BLOCK")
        # The image survives a copy-only repair and must remain in the audit.
        repaired_claims = report["repaired_verification"]["claims"]
        self.assertTrue(any(
            claim.get("source") in {"IMAGE_TEXT", "IMAGE_VISUAL", "IMAGE_AND_AD_COPY"}
            for claim in repaired_claims
        ), repaired_claims)

    def test_safe_campaign_passes_without_repair(self):
        report = self.run_scenario("safe_campaign")["report"]
        self.assertEqual(report["initial_decision"], "PASS")
        self.assertEqual(report["final_decision"], "PASS")
        self.assertFalse(report.get("repair"))

    def test_initial_verifier_timeout_cannot_approve_campaign(self):
        report = self.run_scenario("verifier_timeout")["report"]
        self.assertIsNone(report["initial_decision"])
        self.assertIsNone(report["repaired_decision"])
        self.assertEqual(report["final_decision"], "HUMAN_REVIEW")
        self.assertTrue(report["errors"])

    def test_reverification_timeout_preserves_known_initial_decision(self):
        report = self.run_scenario("reverification_timeout")["report"]
        self.assertEqual(report["initial_decision"], "BLOCK")
        self.assertIsNone(report["repaired_decision"])
        self.assertEqual(report["final_decision"], "BLOCK")
        self.assertEqual(report["workflow_status"], "PARTIAL")
        self.assertTrue(report["human_review_reasons"])
        self.assertTrue(report["errors"])

    def test_transient_failure_has_one_retry_and_eventually_passes(self):
        result = self.run_scenario("transient_retry")
        self.assertEqual(result["report"]["final_decision"], "PASS")
        retries = [event for event in result["events"] if event["type"] == "retry"]
        self.assertEqual(len(retries), 1, result["events"])

    def test_retry_budget_is_bounded_on_persistent_timeout(self):
        result = self.run_scenario("verifier_timeout")
        retries = [event for event in result["events"] if event["type"] == "retry"]
        self.assertLessEqual(len(retries), 1, result["events"])

    def test_events_are_ordered_correlated_and_useful_for_trace_ui(self):
        result = self.run_scenario("copy_repair")
        events = result["events"]
        self.assertGreater(len(events), 3)
        self.assertEqual([event["seq"] for event in events],
                         sorted({event["seq"] for event in events}))
        required = {"seq", "type", "stage", "agent", "phase", "message",
                    "elapsed_ms", "data"}
        for event in events:
            self.assertTrue(required.issubset(event), event)
            self.assertGreaterEqual(event["elapsed_ms"], 0)
            self.assertTrue(event["message"])

    def test_reply_for_another_candidate_is_rejected(self):
        actual_verify = specialists.verify_campaign

        async def mismatched_reply(request):
            reply = await actual_verify(request)
            reply["candidate_id"] = "another-campaign"
            return reply

        with patch("adproof.specialists.verify_campaign", mismatched_reply):
            report = self.run_scenario("copy_repair")["report"]
        self.assertIsNone(report["initial_decision"])
        self.assertEqual(report["final_decision"], "HUMAN_REVIEW")
        self.assertEqual(report["errors"][0]["code"], "INVALID_SPECIALIST_RESPONSE")

    def test_unknown_verifier_decision_is_rejected(self):
        actual_verify = specialists.verify_campaign

        async def invalid_decision(request):
            reply = await actual_verify(request)
            reply["decision"] = "PROBABLY_FINE"
            return reply

        with patch("adproof.specialists.verify_campaign", invalid_decision):
            report = self.run_scenario("safe_campaign")["report"]
        self.assertIsNone(report["initial_decision"])
        self.assertEqual(report["final_decision"], "HUMAN_REVIEW")

    def test_remediator_cannot_approve_its_own_repair(self):
        actual_repair = specialists.repair_copy

        async def self_approved_repair(request):
            reply = await actual_repair(request)
            reply["decision"] = "PASS"
            return reply

        with patch("adproof.specialists.repair_copy", self_approved_repair):
            report = self.run_scenario("copy_repair")["report"]
        self.assertEqual(report["initial_decision"], "BLOCK")
        self.assertEqual(report["final_decision"], "BLOCK")
        self.assertIsNone(report["repaired_decision"])
        self.assertEqual(report["errors"][0]["code"], "INVALID_SPECIALIST_RESPONSE")

    def test_image_changed_during_copy_repair_requires_fresh_audit(self):
        actual_inspect = specialists.inspect_creative

        async def changed_image(campaign, *, phase):
            reply = await actual_inspect(campaign, phase=phase)
            if phase == "REPAIRED":
                reply["image_sha256"] = "changed-image"
            return reply

        with patch("adproof.specialists.inspect_creative", changed_image):
            report = self.run_scenario("copy_repair")["report"]
        self.assertEqual(report["initial_decision"], "BLOCK")
        self.assertEqual(report["final_decision"], "BLOCK")
        self.assertIsNone(report["repaired_decision"])
        self.assertEqual(report["errors"][0]["code"], "IMAGE_SNAPSHOT_MISMATCH")

    def test_same_owner_and_request_replays_a_single_audit(self):
        first, first_replay = self.manager.submit(
            "copy_repair", request_id="replay-example", owner=self.owner)
        second, second_replay = self.manager.submit(
            "copy_repair", request_id="replay-example", owner=self.owner)
        self.assertFalse(first_replay)
        self.assertTrue(second_replay)
        self.assertEqual(first["audit_id"], second["audit_id"])
        final = self.manager.wait(first["audit_id"], self.owner, timeout=5.0)
        third, third_replay = self.manager.submit(
            "copy_repair", request_id="replay-example", owner=self.owner)
        self.assertTrue(third_replay)
        self.assertEqual(third["audit_id"], final["audit_id"])

    def test_same_request_with_different_input_is_conflict(self):
        self.manager.submit("copy_repair", request_id="conflict", owner=self.owner)
        self.assert_error_code(
            lambda: self.manager.submit("safe_campaign", request_id="conflict",
                                        owner=self.owner),
            409,
        )

    def test_different_owner_cannot_read_another_owners_audit(self):
        snapshot, _ = self.manager.submit("safe_campaign", owner=self.owner)
        self.assert_error_code(
            lambda: self.manager.get(snapshot["audit_id"], "someone-else"), 404)

    def test_request_ids_are_scoped_to_the_owner(self):
        first, _ = self.manager.submit(
            "safe_campaign", request_id="shared-key", owner="owner-a")
        second, replayed = self.manager.submit(
            "safe_campaign", request_id="shared-key", owner="owner-b")
        self.assertFalse(replayed)
        self.assertNotEqual(first["audit_id"], second["audit_id"])

    def test_concurrent_duplicate_submissions_start_one_audit(self):
        count = 8
        barrier = Barrier(count)

        def submit(_):
            barrier.wait(timeout=3.0)
            return self.manager.submit("copy_repair", request_id="concurrent-key",
                                       owner=self.owner)

        with ThreadPoolExecutor(max_workers=count) as executor:
            submissions = list(executor.map(submit, range(count)))
        audit_ids = {snapshot["audit_id"] for snapshot, _ in submissions}
        self.assertEqual(len(audit_ids), 1)
        self.assertEqual(sum(not replayed for _, replayed in submissions), 1)
        final = self.manager.wait(next(iter(audit_ids)), self.owner, timeout=5.0)
        self.assertEqual(final["report"]["final_decision"], "PASS")


if __name__ == "__main__":
    unittest.main()
