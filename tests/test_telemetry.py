import json

import sentry_sdk

import adproof.infrastructure.telemetry as telemetry
from adproof.infrastructure.settings import Settings
from adproof.infrastructure.telemetry import (
    _before_send,
    _before_send_log,
    initialize_telemetry,
    record_event,
    stage_span,
)


def test_event_and_log_scrub_sensitive_copy_prompts_sources_urls_and_credentials():
    payload = {
        "ad_copy": "AeroBeat is completely waterproof.",
        "prompt": "extract every claim",
        "source_body": "private page contents",
        "url": "https://shop.example/product?session=private&variant=secret",
        "headers": {
            "Authorization": "Bearer private-token",
            "X-Api-Key": "private-api-key",
        },
        "message": "GEMINI_API_KEY=private-gemini-key DSN=https://private@sentry.example/123",
    }
    for scrubbed in (_before_send(payload, {}), _before_send_log(payload, {})):
        serialized = json.dumps(scrubbed)
        for private_value in (
            "completely waterproof",
            "extract every claim",
            "private page contents",
            "session=private",
            "variant=secret",
            "private-token",
            "private-api-key",
            "private-gemini-key",
            "https://private@sentry.example/123",
        ):
            assert private_value not in serialized


def test_sentry_init_failure_and_absent_dsn_do_not_raise(monkeypatch):
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: (_ for _ in ()).throw(RuntimeError()))
    assert not initialize_telemetry(Settings(sentry_dsn="https://dsn@example.test/1"), role="test")
    assert not initialize_telemetry(Settings(sentry_dsn=None), role="test")
    record_event("audit_completed", role="test", result="PASS")


def test_stage_span_records_duration_and_outcome(monkeypatch):
    events = []
    monkeypatch.setattr(
        telemetry,
        "record_event",
        lambda name, **fields: events.append((name, fields)),
    )
    with stage_span("evidence_assessment", audit_id="audit", role="verifier"):
        pass
    assert events[0][0] == "stage_finished"
    assert events[0][1]["stage"] == "evidence_assessment"
    assert events[0][1]["duration"] >= 0
    assert events[0][1]["result"] == "success"
