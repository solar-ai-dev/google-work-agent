"""SQLite-backed repository implementations for Phase A product core."""

import sqlite3
from json import dumps, loads

from google_work_agent.domain import (
    CommandResult,
    ResultCode,
    RunCommand,
    RunStatus,
    transition_run,
)
from google_work_agent.ports import (
    AnswerOnlyResponse,
    AuditEventRecord,
    CommandReceiptRecord,
    CommandReceiptStatus,
    ConversationRecord,
    MessageRecord,
    RunRecord,
)


class SQLiteConversationRepository:
    """SQLite conversation repository."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get_by_id(self, conversation_id: str) -> ConversationRecord | None:
        row = self._connection.execute(
            """
            SELECT id, account_id, title, created_at_ms, updated_at_ms
            FROM conversations
            WHERE id = ?;
            """,
            (conversation_id,),
        ).fetchone()
        if row is None:
            return None
        return ConversationRecord(
            id=str(row["id"]),
            account_id=str(row["account_id"]),
            title=str(row["title"]),
            created_at_ms=int(row["created_at_ms"]),
            updated_at_ms=int(row["updated_at_ms"]),
        )


class SQLiteRunRepository:
    """SQLite run repository with optimistic state transitions."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get_by_id(self, run_id: str) -> RunRecord | None:
        row = self._connection.execute(
            """
            SELECT id, conversation_id, status, version, started_at_ms, finished_at_ms
            FROM runs
            WHERE id = ?;
            """,
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        return RunRecord(
            id=str(row["id"]),
            conversation_id=str(row["conversation_id"]),
            status=RunStatus(str(row["status"])),
            version=int(row["version"]),
            started_at_ms=int(row["started_at_ms"]),
            finished_at_ms=_int_or_none(row["finished_at_ms"]),
        )

    def complete_answer_only_run(
        self,
        run_id: str,
        *,
        expected_version: int,
        finished_at_ms: int,
    ) -> CommandResult[RunStatus, RunCommand]:
        current = self.get_by_id(run_id)
        if current is None:
            raise LookupError(f"run not found: {run_id}")

        result = transition_run(
            current.status,
            command=RunCommand.COMPLETE_ANSWER_ONLY_RUN,
            current_version=current.version,
            expected_version=expected_version,
        )
        if not result.applied:
            return result

        cursor = self._connection.execute(
            """
            UPDATE runs
            SET status = ?, version = ?, finished_at_ms = ?
            WHERE id = ? AND version = ?;
            """,
            (
                result.current_status.value,
                result.current_version,
                finished_at_ms,
                run_id,
                current.version,
            ),
        )
        if cursor.rowcount != 1:
            raise sqlite3.IntegrityError("answer-only run update affected an unexpected row count")
        return result


class SQLiteMessageRepository:
    """SQLite message repository."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add(self, message: MessageRecord) -> None:
        self._connection.execute(
            """
            INSERT INTO messages (id, conversation_id, run_id, role, content, created_at_ms)
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            (
                message.id,
                message.conversation_id,
                message.run_id,
                message.role,
                message.content,
                message.created_at_ms,
            ),
        )

    def find_assistant_message(
        self,
        *,
        run_id: str,
        content: str,
    ) -> MessageRecord | None:
        row = self._connection.execute(
            """
            SELECT id, conversation_id, run_id, role, content, created_at_ms
            FROM messages
            WHERE run_id = ? AND role = 'ASSISTANT' AND content = ?
            ORDER BY created_at_ms DESC, id DESC
            LIMIT 1;
            """,
            (run_id, content),
        ).fetchone()
        if row is None:
            return None
        return MessageRecord(
            id=str(row["id"]),
            conversation_id=str(row["conversation_id"]),
            run_id=None if row["run_id"] is None else str(row["run_id"]),
            role=str(row["role"]),
            content=str(row["content"]),
            created_at_ms=int(row["created_at_ms"]),
        )


class SQLiteCommandReceiptRepository:
    """SQLite command receipt repository."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get_by_command_id(self, command_id: str) -> CommandReceiptRecord | None:
        row = self._connection.execute(
            """
            SELECT command_id, command_type, request_hash, aggregate_type, aggregate_id,
                   status, result_code, result_version, response_json, created_at_ms,
                   completed_at_ms
            FROM command_receipts
            WHERE command_id = ?;
            """,
            (command_id,),
        ).fetchone()
        if row is None:
            return None
        response = None
        if row["response_json"] is not None:
            response = _deserialize_answer_only_response(str(row["response_json"]))
        return CommandReceiptRecord(
            command_id=str(row["command_id"]),
            command_type=str(row["command_type"]),
            request_hash=str(row["request_hash"]),
            aggregate_type=str(row["aggregate_type"]),
            aggregate_id=None if row["aggregate_id"] is None else str(row["aggregate_id"]),
            status=CommandReceiptStatus(str(row["status"])),
            result_code=None if row["result_code"] is None else ResultCode(str(row["result_code"])),
            result_version=_int_or_none(row["result_version"]),
            response=response,
            created_at_ms=int(row["created_at_ms"]),
            completed_at_ms=_int_or_none(row["completed_at_ms"]),
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
            """
            INSERT INTO command_receipts (
                command_id, command_type, request_hash, aggregate_type, aggregate_id,
                status, created_at_ms
            )
            VALUES (?, ?, ?, ?, ?, 'RECEIVED', ?);
            """,
            (command_id, command_type, request_hash, aggregate_type, aggregate_id, created_at_ms),
        )

    def finish(
        self,
        *,
        command_id: str,
        response: AnswerOnlyResponse,
        completed_at_ms: int,
    ) -> None:
        status = CommandReceiptStatus.APPLIED if response.applied else CommandReceiptStatus.REJECTED
        cursor = self._connection.execute(
            """
            UPDATE command_receipts
            SET status = ?, result_code = ?, result_version = ?,
                response_json = ?, completed_at_ms = ?
            WHERE command_id = ?;
            """,
            (
                status.value,
                response.result_code.value,
                response.current_version,
                _serialize_answer_only_response(response),
                completed_at_ms,
                command_id,
            ),
        )
        if cursor.rowcount != 1:
            raise sqlite3.IntegrityError("receipt finalize affected an unexpected row count")


class SQLiteAuditRepository:
    """Append-only SQLite audit repository."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add(self, event: AuditEventRecord) -> None:
        self._connection.execute(
            """
            INSERT INTO audit_events (
                account_id, run_id, action_id, actor_type, actor_id, actor_display,
                event_type, outcome, metadata_json, created_at_ms
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                event.account_id,
                event.run_id,
                event.action_id,
                event.actor_type,
                event.actor_id,
                event.actor_display,
                event.event_type,
                event.outcome,
                event.metadata_json,
                event.created_at_ms,
            ),
        )


def _serialize_answer_only_response(response: AnswerOnlyResponse) -> str:
    return dumps(
        {
            "applied": response.applied,
            "result_code": response.result_code.value,
            "current_status": response.current_status.value,
            "current_version": response.current_version,
            "next_allowed_commands": [command.value for command in response.next_allowed_commands],
            "conflict_detail": response.conflict_detail,
            "assistant_message_id": response.assistant_message_id,
        },
        sort_keys=True,
    )


def _deserialize_answer_only_response(raw: str) -> AnswerOnlyResponse:
    payload = loads(raw)
    return AnswerOnlyResponse(
        applied=bool(payload["applied"]),
        result_code=ResultCode(str(payload["result_code"])),
        current_status=RunStatus(str(payload["current_status"])),
        current_version=int(payload["current_version"]),
        next_allowed_commands=tuple(
            RunCommand(str(command_value)) for command_value in payload["next_allowed_commands"]
        ),
        conflict_detail=payload["conflict_detail"],
        assistant_message_id=payload["assistant_message_id"],
    )


def _int_or_none(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value)
    raise TypeError(f"expected int-compatible value, got {type(value)!r}")
