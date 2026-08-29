"""SQLite command-receipt repository including durable cancel intent."""

import sqlite3

from google_work_agent.domain.command_receipt.model import CommandReceipt as CommandReceiptRecord
from google_work_agent.domain.command_receipt.model import CommandReceiptStatus
from google_work_agent.domain.results import ResultCode

_REQUEST_CANCEL_COMMAND_TYPE = "RequestRunCancellation"
_RUN_AGGREGATE_TYPE = "Run"


class SqliteCommandReceiptRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get_by_command_id(self, command_id: str) -> CommandReceiptRecord | None:
        r = self._connection.execute(
            """SELECT command_id, command_type, request_hash, aggregate_type,
                      aggregate_id, status, result_code, result_version,
                      response_json, created_at_ms, completed_at_ms
               FROM command_receipts WHERE command_id=?;""",
            (command_id,),
        ).fetchone()
        if r is None:
            return None
        return CommandReceiptRecord(
            command_id=str(r["command_id"]),
            command_type=str(r["command_type"]),
            request_hash=str(r["request_hash"]),
            aggregate_type=str(r["aggregate_type"]),
            aggregate_id=None if r["aggregate_id"] is None else str(r["aggregate_id"]),
            status=CommandReceiptStatus(str(r["status"])),
            result_code=None if r["result_code"] is None else ResultCode(str(r["result_code"])),
            result_version=None if r["result_version"] is None else int(r["result_version"]),
            response=None,
            response_json=None if r["response_json"] is None else str(r["response_json"]),
            created_at_ms=int(r["created_at_ms"]),
            completed_at_ms=None if r["completed_at_ms"] is None else int(r["completed_at_ms"]),
        )

    def reserve_or_replay(
        self,
        *,
        command_id: str,
        command_type: str,
        request_hash: str,
        aggregate_type: str,
        aggregate_id: str | None,
        created_at_ms: int,
    ) -> CommandReceiptRecord | None:
        existing = self.get_by_command_id(command_id)
        if existing is not None:
            return existing
        self._connection.execute(
            """INSERT INTO command_receipts (
                   command_id, command_type, request_hash, aggregate_type,
                   aggregate_id, status, created_at_ms
               ) VALUES (?, ?, ?, ?, ?, 'RECEIVED', ?);""",
            (command_id, command_type, request_hash, aggregate_type, aggregate_id, created_at_ms),
        )
        return None

    def store_result(
        self,
        *,
        command_id: str,
        applied: bool,
        result_code: ResultCode,
        result_version: int,
        response_json: str,
        completed_at_ms: int,
    ) -> None:
        status = CommandReceiptStatus.APPLIED if applied else CommandReceiptStatus.REJECTED
        c = self._connection.execute(
            """UPDATE command_receipts
               SET status=?, result_code=?, result_version=?, response_json=?, completed_at_ms=?
               WHERE command_id=? AND status='RECEIVED';""",
            (
                status.value,
                result_code.value,
                result_version,
                response_json,
                completed_at_ms,
                command_id,
            ),
        )
        if c.rowcount != 1:
            raise sqlite3.IntegrityError("receipt finalize affected an unexpected row count")
