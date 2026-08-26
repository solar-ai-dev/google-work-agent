"""SQLite verification repository."""

import sqlite3

from google_work_agent.domain.verification.model import Verification as VerificationRecord
from google_work_agent.domain.verification.model import VerificationStatus


class SQLiteVerificationRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def insert(self, record: VerificationRecord) -> None:
        self._connection.execute(
            "INSERT INTO verifications (id, execution_attempt_id, verification_no, status, normalizer_version, expected_json, actual_json, diff_json, verified_at_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
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

    def list_by_attempt(self, execution_attempt_id: str) -> tuple[VerificationRecord, ...]:
        rows = self._connection.execute(
            "SELECT id, execution_attempt_id, verification_no, status, normalizer_version, expected_json, actual_json, diff_json, verified_at_ms FROM verifications WHERE execution_attempt_id = ? ORDER BY verification_no ASC;",
            (execution_attempt_id,),
        ).fetchall()
        return tuple(
            VerificationRecord(
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
            for r in rows
        )
