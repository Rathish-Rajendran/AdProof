"""Real local HTTP checks; no external services or credentials."""

import http.cookiejar
import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener

from adproof.server import DemoServer
from adproof.workflow import AuditManager


class LocalAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manager = AuditManager(step_delay=0)
        cls.server = DemoServer(("127.0.0.1", 0), cls.manager)
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.manager.close()
        cls.thread.join(timeout=2)

    def setUp(self):
        self.client = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(self, path, payload=None, client=None, headers=None):
        request = Request(self.base + path,
                          data=json.dumps(payload).encode() if payload is not None else None,
                          headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with (client or self.client).open(request, timeout=3) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    def test_health_labels_the_simulation(self):
        status, data = self.request("/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(data["execution_mode"], "MOCK")
        self.assertEqual(data["live_services_called"], [])

    def test_scenario_catalog_is_available(self):
        status, data = self.request("/api/scenarios")
        self.assertEqual(status, 200)
        self.assertEqual(len(data["scenarios"]), 6)

    def test_submit_complete_download_and_replay(self):
        body = {"scenario_id": "copy_repair", "request_id": "http-test-001"}
        status, accepted = self.request("/api/audits", body)
        self.assertEqual(status, 202)
        self.assertFalse(accepted["replayed"])
        # Poll the actual endpoint with the same browser cookie.
        for _ in range(100):
            _, snapshot = self.request(accepted["status_url"])
            if snapshot["workflow_status"] != "RUNNING":
                break
        self.assertEqual(snapshot["report"]["final_decision"], "PASS")
        status, report = self.request(accepted["status_url"] + "/report")
        self.assertEqual(status, 200)
        self.assertEqual(report["audit_id"], accepted["audit_id"])
        _, replay = self.request("/api/audits", body)
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["audit_id"], accepted["audit_id"])

    def test_other_browser_cannot_read_report(self):
        _, accepted = self.request("/api/audits", {"scenario_id": "unsafe_image"})
        stranger = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
        status, data = self.request(accepted["status_url"], client=stranger)
        self.assertEqual(status, 404)
        self.assertEqual(data["error"]["code"], "NOT_FOUND")

    def test_rejects_external_origin(self):
        status, data = self.request("/api/audits", {"scenario_id": "copy_repair"}, headers={"Origin": "https://different.example"})
        self.assertEqual(status, 403)
        self.assertEqual(data["error"]["code"], "INVALID_ORIGIN")

    def test_rejects_bad_campaign_without_starting_audit(self):
        status, data = self.request("/api/audits", {"scenario_id": "copy_repair", "campaign": {}})
        self.assertEqual(status, 400)
        self.assertEqual(data["error"]["code"], "INVALID_INPUT")


if __name__ == "__main__":
    unittest.main()
