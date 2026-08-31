"""SQLite execution-attempt repository."""

import sqlite3
from typing import cast

from google_work_agent.domain.execution_attempt.model import (
    ExecutionAttempt as ExecutionAttemptRecord,
)
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.ports.persistence.execution_attempt_repository import (
    ExecutionReconciliationCandidateKindV1,
    ExecutionReconciliationCandidateV1,
)


class SqliteExecutionAttemptRepository:
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
            status=ExecutionAttemptStatusV1(str(r["status"])),
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

    def get(self, attempt_id: str) -> ExecutionAttemptRecord | None:
        r = self._connection.execute(self._SELECT + " WHERE id=?;", (attempt_id,)).fetchone()
        return None if r is None else self._record(r)

    def get_active_for_approval(self, approval_id: str) -> ExecutionAttemptRecord | None:
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
        expected_version: int,
        expected_statuses: frozenset[ExecutionAttemptStatusV1],
        values: dict[str, object],
    ) -> bool:
        if not values or not expected_statuses:
            raise ValueError("ExecutionAttempt CAS requires values and expected statuses")
        allowed_columns = {
            "status",
            "version",
            "result_resource_ref_id",
            "response_metadata_json",
            "error_code",
            "error_detail_json",
            "finished_at_ms",
        }
        if not set(values).issubset(allowed_columns):
            raise ValueError("ExecutionAttempt CAS contains an unsupported column")
        normalized = {
            key: value.value if isinstance(value, ExecutionAttemptStatusV1) else value
            for key, value in values.items()
        }
        set_clause = ", ".join(f"{column}=?" for column in normalized)
        placeholders = ", ".join("?" for _ in expected_statuses)
        cursor = self._connection.execute(
            f"UPDATE execution_attempts SET {set_clause} "
            f"WHERE id=? AND version=? AND status IN ({placeholders});",
            [
                *normalized.values(),
                attempt_id,
                expected_version,
                *(status.value for status in expected_statuses),
            ],
        )
        return cursor.rowcount == 1

    def list_reconciliation_candidates(
        self, limit: int
    ) -> tuple[ExecutionReconciliationCandidateV1, ...]:
        if limit < 1 or limit > 256:
            raise ValueError("reconciliation limit must be between 1 and 256")
        rows = self._connection.execute(
            """
            WITH classified AS (
            SELECT ea.id AS execution_attempt_id, a.id AS action_id, p.run_id,
                   ea.started_at_ms,
                   CASE
                     WHEN ea.status='CLAIMED' AND a.status='EXECUTING'
                          AND NOT EXISTS (
                            SELECT 1 FROM command_receipts begin_receipt
                            WHERE begin_receipt.command_type='BeginExecutionAttempt'
                              AND begin_receipt.aggregate_type='ExecutionAttempt'
                              AND begin_receipt.aggregate_id=ea.id
                              AND begin_receipt.status='APPLIED'
                              AND begin_receipt.result_code='TRANSITION_APPLIED'
                          )
                       THEN 'PRE_BEGIN_ORPHAN'
                     WHEN ea.status='EXECUTING' AND a.status='EXECUTING'
                          AND EXISTS (
                            SELECT 1 FROM command_receipts begin_receipt
                            WHERE begin_receipt.command_type='BeginExecutionAttempt'
                              AND begin_receipt.aggregate_type='ExecutionAttempt'
                              AND begin_receipt.aggregate_id=ea.id
                              AND begin_receipt.status='APPLIED'
                              AND begin_receipt.result_code='TRANSITION_APPLIED'
                          )
                       THEN 'POST_BEGIN_ORPHAN'
                     WHEN ea.status='UNKNOWN_RESULT' AND a.status='UNKNOWN_RESULT'
                          AND NOT EXISTS (
                            SELECT 1 FROM recovery_contexts rc
                            WHERE rc.run_id=p.run_id AND rc.reason='UNKNOWN_RESULT'
                              AND rc.action_id=a.id
                              AND rc.execution_attempt_id=ea.id
                          ) THEN 'UNKNOWN_RESULT_UNRESOLVED'
                     WHEN ea.status='SUCCEEDED' AND a.status='EXECUTED'
                          AND NOT EXISTS (
                            SELECT 1 FROM verifications v
                            WHERE v.execution_attempt_id=ea.id
                          ) THEN 'EXECUTED_AWAITING_VERIFICATION'
                     WHEN ea.status='FAILED' AND a.status='FAILED'
                          AND p.status='WAITING_APPROVAL'
                          AND p.revision_no=(
                            SELECT MAX(current_plan.revision_no)
                            FROM plans current_plan
                            WHERE current_plan.run_id=p.run_id
                          )
                          AND EXISTS (
                            SELECT 1 FROM command_receipts resolved
                            WHERE resolved.command_id=(
                                'system:execution-attempt-reconcile:' || ea.id || ':resolve-failed'
                            )
                              AND resolved.command_type='ResolveAsFailed'
                              AND resolved.status='APPLIED'
                              AND resolved.result_code='TRANSITION_APPLIED'
                          ) AND (
                          (r.status='CANCEL_REQUESTED' AND EXISTS (
                            SELECT 1 FROM command_receipts cancel_receipt
                            WHERE cancel_receipt.command_type='RequestRunCancellation'
                              AND cancel_receipt.aggregate_type='Run'
                              AND cancel_receipt.aggregate_id=p.run_id
                              AND cancel_receipt.status='APPLIED'
                              AND cancel_receipt.result_code='TRANSITION_APPLIED'
                          )) OR (r.status IN ('WAITING_APPROVAL','VERIFYING') AND EXISTS (
                            SELECT 1 FROM actions sibling
                            WHERE sibling.plan_id=p.id AND sibling.status='APPROVED'
                              AND NOT EXISTS (
                                SELECT 1
                                FROM action_dependencies dependency
                                JOIN actions predecessor
                                  ON predecessor.id=dependency.depends_on_action_id
                                WHERE dependency.action_id=sibling.id
                                  AND predecessor.status <> 'VERIFIED'
                              )
                          ))
                     ) THEN 'FAILED_AWAITING_CONTINUATION'
                   END AS kind
            FROM execution_attempts ea
            JOIN approvals ap ON ap.id=ea.approval_id
            JOIN actions a ON a.id=ap.action_id
            JOIN plans p ON p.id=a.plan_id
            JOIN runs r ON r.id=p.run_id
            WHERE ea.status IN ('CLAIMED','EXECUTING','UNKNOWN_RESULT','SUCCEEDED','FAILED')
            )
            SELECT execution_attempt_id, action_id, run_id, kind
            FROM classified
            WHERE kind IS NOT NULL
            ORDER BY started_at_ms, execution_attempt_id
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return tuple(
            ExecutionReconciliationCandidateV1(
                schema_version=1,
                kind=cast(ExecutionReconciliationCandidateKindV1, str(row["kind"])),
                execution_attempt_id=str(row["execution_attempt_id"]),
                action_id=str(row["action_id"]),
                run_id=str(row["run_id"]),
            )
            for row in rows
        )
