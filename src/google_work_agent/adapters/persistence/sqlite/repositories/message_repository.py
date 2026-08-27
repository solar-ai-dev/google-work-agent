"""SQLite Message repository adapter."""

from __future__ import annotations

import sqlite3

from google_work_agent.domain.message.model import Message as MessageRecord


class SqliteMessageRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def append_user_message(self, message: MessageRecord) -> None:
        if message.role != "USER":
            raise ValueError("append_user_message requires role USER")
        self._insert(message)

    def append_terminal_assistant_message(self, message: MessageRecord) -> None:
        if message.role != "ASSISTANT" or message.run_id is None:
            raise ValueError("append_terminal_assistant_message requires a run-owned ASSISTANT")
        self._insert(message)

    def list_by_conversation_keyset(
        self,
        *,
        conversation_id: str,
        cursor: str | None,
        page_size: int,
    ) -> tuple[tuple[MessageRecord, ...], str | None]:
        predicate = "WHERE conversation_id = ?"
        params: list[object] = [conversation_id]
        if cursor is not None:
            raw_time, message_id = cursor.split(":", 1)
            created_at_ms = int(raw_time)
            predicate += " AND (created_at_ms < ? OR (created_at_ms = ? AND id < ?))"
            params.extend([created_at_ms, created_at_ms, message_id])
        params.append(page_size + 1)
        rows = self._connection.execute(
            f"""
            SELECT id, conversation_id, run_id, role, content, created_at_ms
            FROM messages
            {predicate}
            ORDER BY created_at_ms DESC, id DESC
            LIMIT ?;
            """,
            tuple(params),
        ).fetchall()
        items = tuple(_record_from_row(row) for row in rows[:page_size])
        next_cursor = None
        if len(rows) > page_size and items:
            last = items[-1]
            next_cursor = f"{last.created_at_ms}:{last.id}"
        return items, next_cursor

    def _insert(self, message: MessageRecord) -> None:
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


def _record_from_row(row: sqlite3.Row) -> MessageRecord:
    return MessageRecord(
        id=str(row["id"]),
        conversation_id=str(row["conversation_id"]),
        run_id=None if row["run_id"] is None else str(row["run_id"]),
        role=str(row["role"]),
        content=str(row["content"]),
        created_at_ms=int(row["created_at_ms"]),
    )
