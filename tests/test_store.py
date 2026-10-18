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
