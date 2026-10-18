"""Loopback-only HTTP adapter for the local orchestration workbench."""

from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import time
from urllib.parse import urlsplit
import uuid

from .errors import DemoError
from .fixtures import LANDING, list_scenarios
from .workflow import AuditManager


ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"


class DemoServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, manager=None):
        self.manager = manager or AuditManager()
        super().__init__(address, DemoHandler)


class DemoHandler(BaseHTTPRequestHandler):
    server_version = "AdProofLocal/0.1"

    def _owner(self):
        if hasattr(self, "_session_owner"):
            return self._session_owner
        jar = cookies.SimpleCookie()
        try:
            jar.load(self.headers.get("Cookie", ""))
        except cookies.CookieError:
            jar = cookies.SimpleCookie()
        value = jar["adproof_session"].value if "adproof_session" in jar else ""
        if not re.fullmatch(r"[0-9a-f]{32}", value):
            value = uuid.uuid4().hex
            self._new_cookie = value
        self._session_owner = value
        return value

    def _send(self, body, status=200, content_type="application/json; charset=utf-8", extra_headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode()
        elif isinstance(body, str):
            body = body.encode()
        self._owner()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        if hasattr(self, "_new_cookie"):
            self.send_header("Set-Cookie", f"adproof_session={self._new_cookie}; HttpOnly; SameSite=Strict; Path=/")
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _error(self, error):
        self._send({"error": error.as_dict()}, error.status)

    def do_GET(self):
        try:
            path = urlsplit(self.path).path
            owner = self._owner()
            if path == "/api/health":
                return self._send({"status": "ok", "execution_mode": "MOCK", "live_services_called": []})
            if path == "/api/scenarios":
                return self._send({"scenarios": list_scenarios()})
            match = re.fullmatch(r"/api/audits/(audit_[0-9a-f]+)(?:/(report|events))?", path)
            if match:
                audit_id, suffix = match.groups()
                snapshot = self.server.manager.get(audit_id, owner)
                if suffix == "events":
                    return self._stream(audit_id, owner)
                if suffix == "report":
                    if snapshot["report"] is None:
                        raise DemoError("AUDIT_RUNNING", "The report is still being prepared.", 409)
                    return self._send(snapshot["report"], extra_headers={"Content-Disposition": f'attachment; filename="{audit_id}.json"'})
                return self._send(snapshot)
            if path == "/fixture/acme-balance":
                return self._send(
                    "<!doctype html><html lang='en'><meta charset='utf-8'><title>Acme Balance · fictional evidence</title>"
                    "<body><h1>Acme Balance</h1><p>Bundled synthetic landing-page fixture.</p>"
                    f"<p>Current price: ${LANDING['current_price']:.2f}</p><p>Previous price: ${LANDING['previous_price']:.2f}</p>"
                    "<p>This fictional page supplies no clinical study or doctor endorsement.</p>"
                    "<p><a href='/'>Return to AdProof</a></p></body></html>",
                    content_type="text/html; charset=utf-8",
                )
            if path == "/fixture/policy":
                return self._send(
                    "<!doctype html><html lang='en'><meta charset='utf-8'><title>Synthetic demo rules</title>"
                    "<body><h1>Synthetic AdProof demo rules</h1><p>These rules exercise the orchestration; they are not legal or platform-policy analysis.</p>"
                    "<ul><li>Unsupported quantified health or clinical-proof claims: critical.</li>"
                    "<li>Unsubstantiated doctor endorsement: major.</li><li>Incorrect listed price or discount: major.</li></ul>"
                    "<p>Critical → BLOCK; major → FIX_REQUIRED; no matched issues → PASS within this fixture.</p>"
                    "<p><a href='/'>Return to AdProof</a></p></body></html>", content_type="text/html; charset=utf-8",
                )
            if path == "/":
                file = STATIC / "index.html"
            elif path.startswith("/static/"):
                file = (STATIC / path.removeprefix("/static/")).resolve()
                if not file.is_relative_to(STATIC.resolve()):
                    raise DemoError("NOT_FOUND", "File not found.", 404)
            else:
                raise DemoError("NOT_FOUND", "Page not found.", 404)
            if not file.is_file():
                raise DemoError("NOT_FOUND", "File not found.", 404)
            media_types = {".html": "text/html", ".css": "text/css", ".js": "text/javascript", ".svg": "image/svg+xml", ".ico": "image/x-icon"}
            return self._send(file.read_bytes(), content_type=media_types.get(file.suffix, "application/octet-stream") + "; charset=utf-8")
        except DemoError as error:
            self._error(error)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _stream(self, audit_id, owner):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        last = -1
        for _ in range(300):
            snapshot = self.server.manager.get(audit_id, owner)
            current = len(snapshot["events"])
            if current != last:
                self.wfile.write(f"event: audit\ndata: {json.dumps(snapshot)}\n\n".encode())
                self.wfile.flush()
                last = current
            if snapshot["workflow_status"] != "RUNNING":
                return
            time.sleep(0.2)

    def do_POST(self):
        try:
            path = urlsplit(self.path).path
            if path != "/api/audits":
                raise DemoError("NOT_FOUND", "Endpoint not found.", 404)
            origin = self.headers.get("Origin")
            if origin and origin != f"http://{self.headers.get('Host')}":
                raise DemoError("INVALID_ORIGIN", "Use the local demo page to submit an audit.", 403)
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                raise DemoError("INVALID_INPUT", "Invalid request size.") from None
            if length < 1 or length > 32768:
                raise DemoError("INVALID_INPUT", "Send a JSON request smaller than 32 KB.")
            try:
                payload = json.loads(self.rfile.read(length))
            except (json.JSONDecodeError, UnicodeDecodeError):
                raise DemoError("INVALID_INPUT", "Request body must be valid JSON.") from None
            if not isinstance(payload, dict):
                raise DemoError("INVALID_INPUT", "Request body must be an object.")
            snapshot, replayed = self.server.manager.submit(
                scenario_id=payload.get("scenario_id", "copy_repair"),
                campaign=payload.get("campaign"), request_id=payload.get("request_id"), owner=self._owner(),
            )
            audit_id = snapshot["audit_id"]
            return self._send({
                "audit_id": audit_id, "status_url": f"/api/audits/{audit_id}",
                "events_url": f"/api/audits/{audit_id}/events", "replayed": replayed,
            }, 202)
        except DemoError as error:
            self._error(error)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, format, *args):
        # Keep the console useful while the UI polls; never log campaign payloads.
        if len(args) > 1 and str(args[1]).startswith(("4", "5")):
            super().log_message(format, *args)
