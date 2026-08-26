"""SQLite execution-attempt repository."""

import sqlite3
from typing import cast

from google_work_agent.domain.execution_attempt.model import (
    ExecutionAttempt as ExecutionAttemptRecord,
)
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatus
from google_work_agent.ports.persistence.execution_attempt_repository import (
    ExecutionReconciliationCandidateKindV1,
    ExecutionReconciliationCandidateV1,
)


class SQLiteExecutionAttemptRepository:
    _SELECT = (
        "SELECT id, approval_id, attempt_no, status, version, result_resource_ref_id, "
        "response_metadata_json, error_code, error_detail_json, started_at_ms, "
        "finished_at_ms FROM execution_attempts"
    )

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    @staticmethod
    def _record(r: sqlite3.Row) -> ExecutionAttemptRecord:
        return ExecutionAttemptRecord(
            id=str(r["id"]),
            approval_id=str(r["approval_id"]),
            attempt_no=int(r["attempt_no"]),
            status=ExecutionAttemptStatus(str(r["status"])),
            version=int(r["version"]),
            result_resource_ref_id=None
            if r["result_resource_ref_id"] is None
            else str(r["result_resource_ref_id"]),
            response_metadata_json=None
            if r["response_metadata_json"] is None
            else str(r["response_metadata_json"]),
            error_code=None if r["error_code"] is None else str(r["error_code"]),
            error_detail_json=None
            if r["error_detail_json"] is None
            else str(r["error_detail_json"]),
            started_at_ms=int(r["started_at_ms"]),
            finished_at_ms=None if r["finished_at_ms"] is None else int(r["finished_at_ms"]),
        )

    def get_by_id(self, attempt_id: str) -> ExecutionAttemptRecord | None:
        r = self._connection.execute(self._SELECT + " WHERE id=?;", (attempt_id,)).fetchone()
        return None if r is None else self._record(r)

    def get_active_by_approval(self, approval_id: str) -> ExecutionAttemptRecord | None:
        r = self._connection.execute(
            self._SELECT + " WHERE approval_id=? AND status IN "
            "('CLAIMED','EXECUTING','UNKNOWN_RESULT') "
            "ORDER BY attempt_no DESC LIMIT 1;",
            (approval_id,),
        ).fetchone()
        return None if r is None else self._record(r)

    def insert_claimed(self, record: ExecutionAttemptRecord) -> None:
        self._connection.execute(
            """INSERT INTO execution_attempts (
                id, approval_id, attempt_no, status, version, result_resource_ref_id,
                response_metadata_json, error_code, error_detail_json,
                started_at_ms, finished_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);""",
            (
                record.id,
                record.approval_id,
                record.attempt_no,
                record.status.value,
                record.version,
                record.result_resource_ref_id,
                record.response_metadata_json,
                record.error_code,
                record.error_detail_json,
                record.started_at_ms,
                record.finished_at_ms,
            ),
        )

    def update_if_version_and_status(
        self,
        attempt_id: str,
        *,
        expected_version: int,
        expected_status: ExecutionAttemptStatus,
        status: ExecutionAttemptStatus,
        error_code: str | None,
        error_detail_json: str | None,
        result_resource_ref_id: str | None,
        response_metadata_json: str | None,
        finished_at_ms: int | None,
    ) -> ExecutionAttemptRecord:
        current = self.get_by_id(attempt_id)
        if current is None:
            raise LookupError(f"execution attempt not found: {attempt_id}")
        if current.version != expected_version:
            raise sqlite3.IntegrityError("execution attempt version conflict")
        c = self._connection.execute(
            """UPDATE execution_attempts SET
                status=?, version=version+1, result_resource_ref_id=?,
                response_metadata_json=?, error_code=?, error_detail_json=?, finished_at_ms=?
            WHERE id=? AND version=? AND status=?;""",
            (
                status.value,
                result_resource_ref_id,
                response_metadata_json,
                error_code,
                error_detail_json,
                finished_at_ms,
                attempt_id,
                expected_version,
                expected_status.value,
            ),
        )
        if c.rowcount != 1:
            raise sqlite3.IntegrityError(
                "execution attempt update affected an unexpected row count"
            )
        updated = self.get_by_id(attempt_id)
        if updated is None:
            raise LookupError(f"execution attempt not found after update: {attempt_id}")
        return updated

    def list_by_approval(self, approval_id: str) -> tuple[ExecutionAttemptRecord, ...]:
        return tuple(
            self._record(r)
            for r in self._connection.execute(
                self._SELECT + " WHERE approval_id=? ORDER BY attempt_no ASC;",
                (approval_id,),
            ).fetchall()
        )

    def list_reconciliation_candidates(
        self, limit: int
    ) -> tuple[ExecutionReconciliationCandidateV1, ...]:
        if limit < 1 or limit > 256:
            raise ValueError("reconciliation limit must be between 1 and 256")
        rows = self._connection.execute(
            """
            SELECT ea.id AS execution_attempt_id, a.id AS action_id, p.run_id,
                   CASE
                     WHEN ea.status='EXECUTING' AND a.status='EXECUTING'
                       THEN 'POST_BEGIN_ORPHAN'
                     WHEN ea.status='UNKNOWN_RESULT' AND a.status='UNKNOWN_RESULT'
                          AND NOT EXISTS (
                            SELECT 1 FROM recovery_contexts rc
                            WHERE rc.run_id=p.run_id AND rc.reason='UNKNOWN_RESULT'
                              AND rc.execution_attempt_id=ea.id
                          ) THEN 'UNKNOWN_RESULT_UNRESOLVED'
                     WHEN ea.status='SUCCEEDED' AND a.status='EXECUTED'
                          AND NOT EXISTS (
                            SELECT 1 FROM verifications v
                            WHERE v.execution_attempt_id=ea.id
                          ) THEN 'EXECUTED_AWAITING_VERIFICATION'
                     WHEN ea.status='FAILED' AND a.status='FAILED' AND (
                          EXISTS (
                            SELECT 1 FROM audit_events au
                            WHERE au.run_id=p.run_id
                              AND au.event_type='RUN_CANCELLATION_REQUESTED'
                          ) OR EXISTS (
                            SELECT 1 FROM actions sibling
                            WHERE sibling.plan_id=p.id AND sibling.status='APPROVED'
                          )
                     ) THEN 'FAILED_AWAITING_CONTINUATION'
                   END AS kind
            FROM execution_attempts ea
            JOIN approvals ap ON ap.id=ea.approval_id
            JOIN actions a ON a.id=ap.action_id
            JOIN plans p ON p.id=a.plan_id
            WHERE ea.status IN ('EXECUTING','UNKNOWN_RESULT','SUCCEEDED','FAILED')
            ORDER BY ea.started_at_ms, ea.id
            """
        ).fetchall()
        candidates = [row for row in rows if row["kind"] is not None]
        return tuple(
            ExecutionReconciliationCandidateV1(
                schema_version=1,
                kind=cast(ExecutionReconciliationCandidateKindV1, str(row["kind"])),
                execution_attempt_id=str(row["execution_attempt_id"]),
                action_id=str(row["action_id"]),
                run_id=str(row["run_id"]),
            )
            for row in candidates[:limit]
        )
