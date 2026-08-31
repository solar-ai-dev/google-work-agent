"""SQLite Approval history projection without widening ApprovalRepository."""

import sqlite3

from google_work_agent.adapters.persistence.sqlite.repositories.approval_repository import (
    APPROVAL_SELECT,
    approval_record_from_row,
)
from google_work_agent.domain.approval.model import Approval


class SqliteApprovalHistoryReader:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get(self, approval_id: str) -> Approval | None:
        row = self._connection.execute(APPROVAL_SELECT + " WHERE id=?;", (approval_id,)).fetchone()
        return None if row is None else approval_record_from_row(row)

    def list_for_action(self, action_id: str) -> tuple[Approval, ...]:
        return tuple(
            approval_record_from_row(row)
            for row in self._connection.execute(
                APPROVAL_SELECT + " WHERE action_id=? ORDER BY approval_no;",
                (action_id,),
            ).fetchall()
        )
