"""SQLite approval repository."""

import sqlite3

from google_work_agent.domain.approval.model import Approval as ApprovalRecord
from google_work_agent.domain.approval.model import ApprovalStatusV1


class SQLiteApprovalRepository:
    _SELECT = "SELECT id, action_id, approval_no, action_version, status, approved_by_account_id, approved_by_display, arguments_snapshot_json, canonical_arguments_hash, source_snapshot_json, source_snapshot_hash, policy_version, tool_schema_version, idempotency_key, recovery_fingerprint, approved_at_ms, expires_at_ms, consumed_at_ms FROM approvals"  # noqa: E501

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    @staticmethod
    def _record(r: sqlite3.Row) -> ApprovalRecord:
        return ApprovalRecord(
            id=str(r["id"]),
            action_id=str(r["action_id"]),
            approval_no=int(r["approval_no"]),
            action_version=int(r["action_version"]),
            status=ApprovalStatusV1(str(r["status"])),
            approved_by_account_id=str(r["approved_by_account_id"]),
            approved_by_display=None
            if r["approved_by_display"] is None
            else str(r["approved_by_display"]),
            arguments_snapshot_json=str(r["arguments_snapshot_json"]),
            canonical_arguments_hash=str(r["canonical_arguments_hash"]),
            source_snapshot_json=str(r["source_snapshot_json"]),
            source_snapshot_hash=str(r["source_snapshot_hash"]),
            policy_version=str(r["policy_version"]),
            tool_schema_version=str(r["tool_schema_version"]),
            idempotency_key=str(r["idempotency_key"]),
            recovery_fingerprint=str(r["recovery_fingerprint"]),
            approved_at_ms=int(r["approved_at_ms"]),
            expires_at_ms=int(r["expires_at_ms"]),
            consumed_at_ms=None if r["consumed_at_ms"] is None else int(r["consumed_at_ms"]),
        )

    def get_by_id(self, approval_id: str) -> ApprovalRecord | None:
        r = self._connection.execute(self._SELECT + " WHERE id=?;", (approval_id,)).fetchone()
        return None if r is None else self._record(r)

    def get_active_by_action(self, action_id: str) -> ApprovalRecord | None:
        r = self._connection.execute(
            self._SELECT
            + " WHERE action_id=? AND status='ACTIVE' ORDER BY approval_no DESC LIMIT 1;",
            (action_id,),
        ).fetchone()
        return None if r is None else self._record(r)

    def insert(self, record: ApprovalRecord) -> None:
        self._connection.execute(
            "INSERT INTO approvals (id, action_id, approval_no, action_version, status, approved_by_account_id, approved_by_display, arguments_snapshot_json, canonical_arguments_hash, source_snapshot_json, source_snapshot_hash, policy_version, tool_schema_version, idempotency_key, recovery_fingerprint, approved_at_ms, expires_at_ms, consumed_at_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",  # noqa: E501
            (
                record.id,
                record.action_id,
                record.approval_no,
                record.action_version,
                record.status.value,
                record.approved_by_account_id,
                record.approved_by_display,
                record.arguments_snapshot_json,
                record.canonical_arguments_hash,
                record.source_snapshot_json,
                record.source_snapshot_hash,
                record.policy_version,
                record.tool_schema_version,
                record.idempotency_key,
                record.recovery_fingerprint,
                record.approved_at_ms,
                record.expires_at_ms,
                record.consumed_at_ms,
            ),
        )

    def update_if_status(
        self,
        approval_id: str,
        *,
        expected_status: ApprovalStatusV1,
        next_status: ApprovalStatusV1,
        consumed_at_ms: int | None = None,
    ) -> bool:
        cursor = self._connection.execute(
            "UPDATE approvals SET status=?, consumed_at_ms=COALESCE(?, consumed_at_ms) WHERE id=? AND status=?;",  # noqa: E501
            (next_status.value, consumed_at_ms, approval_id, expected_status.value),
        )
        if cursor.rowcount > 1:
            raise sqlite3.IntegrityError("approval CAS affected an unexpected row count")
        return cursor.rowcount == 1

    def list_by_action(self, action_id: str) -> tuple[ApprovalRecord, ...]:
        return tuple(
            self._record(r)
            for r in self._connection.execute(
                self._SELECT + " WHERE action_id=? ORDER BY approval_no ASC;", (action_id,)
            ).fetchall()
        )
