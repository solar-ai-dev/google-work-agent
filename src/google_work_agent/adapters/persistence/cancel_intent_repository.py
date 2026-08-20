"""SQLite read adapter for the canonical durable cancel-intent fact."""

from __future__ import annotations

from google_work_agent.adapters.persistence.repositories import SQLiteCommandReceiptRepository
from google_work_agent.application.cancel_intent import is_applied_request_cancel_receipt


class CancelIntentCommandReceiptRepository(SQLiteCommandReceiptRepository):
    """Command receipts with the one durable RequestCancel query."""

    def has_applied_request_cancel(self, run_id: str) -> bool:
        rows = self._connection.execute(
            """
            SELECT command_type, aggregate_type, aggregate_id, status, result_code
            FROM command_receipts
            WHERE command_type = 'RequestRunCancellation'
              AND aggregate_type = 'Run'
              AND aggregate_id = ?
              AND status = 'APPLIED';
            """,
            (run_id,),
        ).fetchall()
        return any(
            is_applied_request_cancel_receipt(
                command_type=str(row["command_type"]),
                aggregate_type=str(row["aggregate_type"]),
                aggregate_id=None if row["aggregate_id"] is None else str(row["aggregate_id"]),
                status=str(row["status"]),
                result_code=None if row["result_code"] is None else str(row["result_code"]),
                run_id=run_id,
            )
            for row in rows
        )
