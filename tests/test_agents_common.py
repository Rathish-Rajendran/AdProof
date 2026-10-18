from __future__ import annotations

from agents import common


def _addresses() -> dict[str, str]:
    return {
        "orchestrator": "agent-orchestrator",
        "verifier": "agent-verifier",
        "remediator": "agent-remediator",
        "generator": "agent-generator",
    }


def test_mailbox_orchestrator_omits_loopback_endpoint(monkeypatch):
    captured = {}

    def fake_agent(**kwargs):
        captured.update(kwargs)
        return kwargs

    monkeypatch.setattr(common, "Agent", fake_agent)
    monkeypatch.setenv("ADPROOF_MAILBOX_ENABLED", "1")
    monkeypatch.setenv("ADPROOF_ORCHESTRATOR_HANDLE", "adproof-test")
    monkeypatch.delenv("ADPROOF_TRANSPORT_PROBE", raising=False)

    common.make_agent(
        role="orchestrator",
        seed="test-seed",
        addresses=_addresses(),
        port=8100,
    )

    assert captured["port"] == 8100
    assert captured["mailbox"] is True
    assert captured["handle"] == "adproof-test"
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
    monkeypatch.setenv("ADPROOF_ORCHESTRATOR_HANDLE", "adproof-test")

    common.make_agent(
        role="verifier",
        seed="test-seed",
        addresses=_addresses(),
        port=8101,
    )

    assert captured["mailbox"] is False
    assert "handle" not in captured
    assert captured["endpoint"] == ["http://127.0.0.1:8101/submit"]
    assert captured["resolve"]._rules["agent-orchestrator"] == "http://127.0.0.1:8100/submit"


def test_orchestrator_handle_is_omitted_without_mailbox(monkeypatch):
    captured = {}

    def fake_agent(**kwargs):
        captured.update(kwargs)
        return kwargs

    monkeypatch.setattr(common, "Agent", fake_agent)
    monkeypatch.setenv("ADPROOF_MAILBOX_ENABLED", "0")
    monkeypatch.setenv("ADPROOF_ORCHESTRATOR_HANDLE", "adproof-test")

    common.make_agent(
        role="orchestrator",
        seed="test-seed",
        addresses=_addresses(),
        port=8100,
    )

    assert captured["mailbox"] is False
    assert "handle" not in captured
    assert captured["endpoint"] == ["http://127.0.0.1:8100/submit"]


def test_public_orchestrator_falls_back_to_global_resolution_for_chat_users():
    import asyncio

    from agents.common import LocalFirstResolver

    class Fallback:
        async def resolve(self, destination):
            return destination, ["https://agentverse.ai/v2/agents/mailbox/submit"]

    resolver = LocalFirstResolver({"agent-verifier": "http://127.0.0.1:8101/submit"}, Fallback())
    assert asyncio.run(resolver.resolve("agent-verifier"))[1] == ["http://127.0.0.1:8101/submit"]
    assert asyncio.run(resolver.resolve("agent-asi-user"))[1] == [
        "https://agentverse.ai/v2/agents/mailbox/submit"
    ]
    assert asyncio.run(LocalFirstResolver({}).resolve("agent-asi-user"))[1] == []
