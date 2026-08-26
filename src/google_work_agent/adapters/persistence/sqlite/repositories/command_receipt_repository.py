"""SQLite command-receipt repository including durable cancel intent."""

import sqlite3
from json import dumps, loads

from google_work_agent.domain.command_receipt.model import AnswerOnlyResponse, CommandReceiptStatus
from google_work_agent.domain.command_receipt.model import CommandReceipt as CommandReceiptRecord
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.run.model import RunCommand, RunStatus

_REQUEST_CANCEL_COMMAND_TYPE = "RequestRunCancellation"
_RUN_AGGREGATE_TYPE = "Run"


class SQLiteCommandReceiptRepository:
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
        response = None
        if r["response_json"] is not None and str(r["command_type"]) == "CompleteAnswerOnlyRun":
            p = loads(str(r["response_json"]))
            response = AnswerOnlyResponse(
                applied=bool(p["applied"]),
                result_code=ResultCode(str(p["result_code"])),
                current_status=RunStatus(str(p["current_status"])),
                current_version=int(p["current_version"]),
                next_allowed_commands=tuple(RunCommand(str(v)) for v in p["next_allowed_commands"]),
                conflict_detail=p["conflict_detail"],
                assistant_message_id=p["assistant_message_id"],
            )
        return CommandReceiptRecord(
            command_id=str(r["command_id"]),
            command_type=str(r["command_type"]),
            request_hash=str(r["request_hash"]),
            aggregate_type=str(r["aggregate_type"]),
            aggregate_id=None if r["aggregate_id"] is None else str(r["aggregate_id"]),
            status=CommandReceiptStatus(str(r["status"])),
            result_code=None if r["result_code"] is None else ResultCode(str(r["result_code"])),
            result_version=None if r["result_version"] is None else int(r["result_version"]),
            response=response,
            response_json=None if r["response_json"] is None else str(r["response_json"]),
            created_at_ms=int(r["created_at_ms"]),
            completed_at_ms=None if r["completed_at_ms"] is None else int(r["completed_at_ms"]),
        )

    def add_received(
        self,
        *,
        command_id: str,
        command_type: str,
        request_hash: str,
        aggregate_type: str,
        aggregate_id: str | None,
        created_at_ms: int,
    ) -> None:
        self._connection.execute(
            """INSERT INTO command_receipts (
                   command_id, command_type, request_hash, aggregate_type,
                   aggregate_id, status, created_at_ms
               ) VALUES (?, ?, ?, ?, ?, 'RECEIVED', ?);""",
            (command_id, command_type, request_hash, aggregate_type, aggregate_id, created_at_ms),
        )

    def finish(
        self, *, command_id: str, response: AnswerOnlyResponse, completed_at_ms: int
    ) -> None:
        raw = dumps(
            {
                "applied": response.applied,
                "result_code": response.result_code.value,
                "current_status": response.current_status.value,
                "current_version": response.current_version,
                "next_allowed_commands": [c.value for c in response.next_allowed_commands],
                "conflict_detail": response.conflict_detail,
                "assistant_message_id": response.assistant_message_id,
            },
            sort_keys=True,
        )
        self.finish_json(
            command_id=command_id,
            applied=response.applied,
            result_code=response.result_code,
            result_version=response.current_version,
            response_json=raw,
            completed_at_ms=completed_at_ms,
        )

    def finish_json(
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
               WHERE command_id=?;""",
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

    def has_applied_request_cancel(self, run_id: str) -> bool:
        row = self._connection.execute(
            """SELECT 1 FROM command_receipts
               WHERE command_type=? AND aggregate_type=? AND aggregate_id=?
                 AND status=? AND result_code=? LIMIT 1;""",
            (
                _REQUEST_CANCEL_COMMAND_TYPE,
                _RUN_AGGREGATE_TYPE,
                run_id,
                CommandReceiptStatus.APPLIED.value,
                ResultCode.TRANSITION_APPLIED.value,
            ),
        ).fetchone()
        return row is not None
