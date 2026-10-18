from __future__ import annotations

from agents import common


def _addresses() -> dict[str, str]:
    return {
        "orchestrator": "agent-orchestrator",
        "verifier": "agent-verifier",
        "remediator": "agent-remediator",
    }


def test_mailbox_orchestrator_omits_loopback_endpoint(monkeypatch):
    captured = {}

    def fake_agent(**kwargs):
        captured.update(kwargs)
        return kwargs

    monkeypatch.setattr(common, "Agent", fake_agent)
    monkeypatch.setenv("ADPROOF_MAILBOX_ENABLED", "1")
    monkeypatch.delenv("ADPROOF_TRANSPORT_PROBE", raising=False)

    common.make_agent(
        role="orchestrator",
        seed="test-seed",
        addresses=_addresses(),
        port=8100,
    )

    assert captured["port"] == 8100
    assert captured["mailbox"] is True
    assert "endpoint" not in captured
    assert captured["resolve"]._rules["agent-verifier"] == "http://127.0.0.1:8101/submit"
    assert captured["resolve"]._rules["agent-remediator"] == "http://127.0.0.1:8102/submit"


def test_specialist_keeps_loopback_endpoint_when_mailbox_is_enabled(monkeypatch):
    captured = {}

    def fake_agent(**kwargs):
        captured.update(kwargs)
        return kwargs

    monkeypatch.setattr(common, "Agent", fake_agent)
    monkeypatch.setenv("ADPROOF_MAILBOX_ENABLED", "1")

    common.make_agent(
        role="verifier",
        seed="test-seed",
        addresses=_addresses(),
        port=8101,
    )

    assert captured["mailbox"] is False
    assert captured["endpoint"] == ["http://127.0.0.1:8101/submit"]
    assert captured["resolve"]._rules["agent-orchestrator"] == "http://127.0.0.1:8100/submit"
