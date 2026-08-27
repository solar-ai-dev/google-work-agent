"""SQLite projection of the immutable receipt-backed cancel fact."""

import sqlite3

from google_work_agent.domain.command_receipt.model import CommandReceiptStatus
from google_work_agent.domain.results import ResultCode


class SqliteCancelIntentReader:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def has_durable_intent(self, run_id: str) -> bool:
        return (
            self._connection.execute(
                """SELECT 1
                   FROM command_receipts
                   WHERE command_type='RequestRunCancellation'
                     AND aggregate_type='Run'
                     AND aggregate_id=?
                     AND status=?
                     AND result_code=?
                   LIMIT 1;""",
                (
                    run_id,
                    CommandReceiptStatus.APPLIED.value,
                    ResultCode.TRANSITION_APPLIED.value,
                ),
            ).fetchone()
            is not None
        )
