from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from adproof.domain.models import TypedErrorCode


class SQLiteStore:
    def __init__(self, path: Path, *, retention: timedelta = timedelta(hours=24)):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = path
        self.retention = retention
        self._initialize()
        self.purge_expired()
        self.interrupt_nonterminal()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS workflows (
                    audit_id TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS idempotency (
                    scope TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    audit_id TEXT NOT NULL,
                    PRIMARY KEY (scope, request_id)
                )"""
            )
        self.path.chmod(0o600)

    def save_workflow(
        self,
        *,
        audit_id: str,
        owner: str,
        session_id: str,
        state: str,
        payload: dict[str, Any],
        now: datetime | None = None,
    ) -> None:
        now = now or datetime.now(UTC)
        expires_at = now + self.retention
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO workflows VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(audit_id) DO UPDATE SET state=excluded.state,
                   payload_json=excluded.payload_json, expires_at=excluded.expires_at""",
                (
                    audit_id,
                    owner,
                    session_id,
                    state,
                    json.dumps(payload),
                    expires_at.isoformat(),
                ),
            )

    def get_workflow(self, audit_id: str, *, owner: str, session_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM workflows WHERE audit_id=? AND owner=? AND session_id=?",
                (audit_id, owner, session_id),
            ).fetchone()
        if row is None or datetime.fromisoformat(row["expires_at"]) <= datetime.now(UTC):
            return None
        return {**dict(row), "payload": json.loads(row["payload_json"])}

    def claim_idempotency(
        self, *, scope: str, request_id: str, payload_hash: str, audit_id: str
    ) -> str | TypedErrorCode:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_hash, audit_id FROM idempotency WHERE scope=? AND request_id=?",
                (scope, request_id),
            ).fetchone()
            if row:
                return (
                    row["audit_id"]
                    if row["payload_hash"] == payload_hash
                    else TypedErrorCode.INVALID_EVIDENCE
                )
            connection.execute(
                "INSERT INTO idempotency VALUES (?, ?, ?, ?)",
                (scope, request_id, payload_hash, audit_id),
            )
        return audit_id

    def interrupt_nonterminal(self) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE workflows SET state=? WHERE state NOT IN ('COMPLETED','PARTIAL','FAILED')",
                (TypedErrorCode.WORKFLOW_INTERRUPTED.value,),
            )
        return cursor.rowcount

    def purge_expired(self, *, now: datetime | None = None) -> int:
        now = now or datetime.now(UTC)
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM workflows WHERE expires_at<=?", (now.isoformat(),)
            )
        return cursor.rowcount
