from datetime import UTC, datetime, timedelta

from adproof.domain.models import TypedErrorCode
from adproof.infrastructure.store import SQLiteStore


def test_store_binds_ownership_idempotency_and_retention(tmp_path):
    store = SQLiteStore(tmp_path / "audit.sqlite3", retention=timedelta(hours=24))
    audit_id = store.claim_idempotency(
        scope="owner:session",
        request_id="request",
        payload_hash="hash",
        audit_id="audit",
    )
    assert audit_id == "audit"
    assert (
        store.claim_idempotency(
            scope="owner:session",
            request_id="request",
            payload_hash="different",
            audit_id="new-audit",
        )
        == TypedErrorCode.INVALID_EVIDENCE
    )
    store.save_workflow(
        audit_id="audit",
        owner="owner",
        session_id="session",
        state="VERIFYING",
        payload={"private": "content"},
    )
    assert store.get_workflow("audit", owner="other", session_id="session") is None
    assert store.get_workflow("audit", owner="owner", session_id="other") is None
    assert (
        store.get_workflow("audit", owner="owner", session_id="session")["payload"]["private"]
        == "content"
    )
    assert store.interrupt_nonterminal() == 1
    assert (
        store.get_workflow("audit", owner="owner", session_id="session")["state"]
        == "WORKFLOW_INTERRUPTED"
    )
    assert store.purge_expired(now=datetime.now(UTC) + timedelta(days=2)) == 1


def test_chat_message_dedupe_and_card_action_idempotency_survive_restart(tmp_path):
    path = tmp_path / "audit.sqlite3"
    store = SQLiteStore(path)
    assert (
        store.claim_chat_message(
            sender="owner",
            session_id="session",
            msg_id="message",
            digest="message-hash",
        )
        == "NEW"
    )
    assert (
        store.claim_card_action(
            owner="owner",
            session_id="session",
            action_id="action",
            digest="action-hash",
        )
        is True
    )

    restarted = SQLiteStore(path)
    assert (
        restarted.claim_chat_message(
            sender="owner",
            session_id="session",
            msg_id="message",
            digest="message-hash",
        )
        == "DUPLICATE"
    )
    assert (
        restarted.claim_chat_message(
            sender="owner",
            session_id="session",
            msg_id="message",
            digest="different",
        )
        == "CONFLICT"
    )
    assert (
        restarted.claim_card_action(
            owner="owner",
            session_id="session",
            action_id="action",
            digest="action-hash",
        )
        is False
    )
