"""SQLite verification repository."""

import sqlite3

from google_work_agent.domain.verification.model import Verification as VerificationRecord
from google_work_agent.domain.verification.model import VerificationStatus


class SqliteVerificationRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def insert(self, record: VerificationRecord) -> None:
        self._connection.execute(
            "INSERT INTO verifications (id, execution_attempt_id, verification_no, status, "
            "normalizer_version, expected_json, actual_json, diff_json, verified_at_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
            (
                record.id,
                record.execution_attempt_id,
                record.verification_no,
                record.status.value,
                record.normalizer_version,
                record.expected_json,
                record.actual_json,
                record.diff_json,
                record.verified_at_ms,
            ),
        )

    def get_latest_for_attempt(self, execution_attempt_id: str) -> VerificationRecord | None:
        row = self._connection.execute(
            "SELECT id, execution_attempt_id, verification_no, status, normalizer_version, "
            "expected_json, actual_json, diff_json, verified_at_ms FROM verifications "
            "WHERE execution_attempt_id = ? ORDER BY verification_no DESC LIMIT 1;",
            (execution_attempt_id,),
        ).fetchone()
        return None if row is None else self._record(row)

    def list_for_action(self, action_id: str) -> tuple[VerificationRecord, ...]:
        rows = self._connection.execute(
            "SELECT v.id, v.execution_attempt_id, v.verification_no, v.status, "
            "v.normalizer_version, v.expected_json, v.actual_json, v.diff_json, "
            "v.verified_at_ms FROM verifications v JOIN execution_attempts ea "
            "ON ea.id=v.execution_attempt_id JOIN approvals ap ON ap.id=ea.approval_id "
            "WHERE ap.action_id=? ORDER BY v.verified_at_ms, v.id;",
            (action_id,),
        ).fetchall()
        return tuple(self._record(row) for row in rows)

    @staticmethod
    def _record(r: sqlite3.Row) -> VerificationRecord:
        return VerificationRecord(
            id=str(r["id"]),
            execution_attempt_id=str(r["execution_attempt_id"]),
            verification_no=int(r["verification_no"]),
            status=VerificationStatus(str(r["status"])),
            normalizer_version=str(r["normalizer_version"]),
            expected_json=str(r["expected_json"]),
            actual_json=None if r["actual_json"] is None else str(r["actual_json"]),
            diff_json=str(r["diff_json"]),
            verified_at_ms=int(r["verified_at_ms"]),
        )
