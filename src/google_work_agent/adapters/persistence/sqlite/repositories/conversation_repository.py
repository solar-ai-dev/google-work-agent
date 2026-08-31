"""SQLite Conversation repository adapter."""

from __future__ import annotations

import sqlite3

from google_work_agent.domain.conversation.model import Conversation as ConversationRecord
from google_work_agent.ports.persistence.conversation_repository import ConversationListRecord


class SqliteConversationRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def create(self, conversation: ConversationRecord) -> None:
        self._connection.execute(
            """
            INSERT INTO conversations (id, account_id, title, created_at_ms, updated_at_ms)
            VALUES (?, ?, ?, ?, ?);
            """,
            (
                conversation.id,
                conversation.account_id,
                conversation.title,
                conversation.created_at_ms,
                conversation.updated_at_ms,
            ),
        )

    def get(self, conversation_id: str) -> ConversationRecord | None:
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
        return _record_from_row(row)

    def list_keyset(
        self,
        *,
        account_id: str,
        cursor: str | None,
        page_size: int,
        search: str | None = None,
    ) -> tuple[tuple[ConversationListRecord, ...], str | None]:
        predicate = "WHERE account_id = ?"
        params: list[object] = [account_id]
        if search is not None:
            pattern = f"%{_escape_like(search)}%"
            predicate += (
                " AND (LOWER(title) LIKE LOWER(?) ESCAPE '\\' OR EXISTS ("
                "SELECT 1 FROM messages m WHERE m.conversation_id=conversations.id "
                "AND LOWER(m.content) LIKE LOWER(?) ESCAPE '\\'))"
            )
            params.extend([pattern, pattern])
        if cursor is not None:
            raw_time, conversation_id = cursor.split(":", 1)
            updated_at_ms = int(raw_time)
            predicate += " AND (updated_at_ms < ? OR (updated_at_ms = ? AND id < ?))"
            params.extend([updated_at_ms, updated_at_ms, conversation_id])
        params.append(page_size + 1)
        rows = self._connection.execute(
            f"""
            SELECT conversations.id, conversations.account_id, conversations.title,
                   conversations.created_at_ms, conversations.updated_at_ms,
                   (SELECT MAX(m.created_at_ms) FROM messages m
                    WHERE m.conversation_id=conversations.id) AS latest_message_at_ms,
                   (SELECT r.id FROM runs r
                    WHERE r.conversation_id=conversations.id AND r.finished_at_ms IS NULL
                    ORDER BY r.started_at_ms DESC, r.id DESC LIMIT 1) AS open_run_id
            FROM conversations
            {predicate}
            ORDER BY updated_at_ms DESC, id DESC
            LIMIT ?;
            """,
            tuple(params),
        ).fetchall()
        items = tuple(
            ConversationListRecord(
                conversation=_record_from_row(row),
                latest_message_at_ms=(
                    None
                    if row["latest_message_at_ms"] is None
                    else int(row["latest_message_at_ms"])
                ),
                open_run_id=None if row["open_run_id"] is None else str(row["open_run_id"]),
            )
            for row in rows[:page_size]
        )
        next_cursor = None
        if len(rows) > page_size and items:
            last = items[-1]
            next_cursor = f"{last.conversation.updated_at_ms}:{last.conversation.id}"
        return items, next_cursor

    def touch_updated_at(self, conversation_id: str, *, updated_at_ms: int) -> None:
        self._connection.execute(
            """
            UPDATE conversations
            SET updated_at_ms = ?
            WHERE id = ? AND updated_at_ms < ?;
            """,
            (updated_at_ms, conversation_id, updated_at_ms),
        )


def _record_from_row(row: sqlite3.Row) -> ConversationRecord:
    return ConversationRecord(
        id=str(row["id"]),
        account_id=str(row["account_id"]),
        title=str(row["title"]),
        created_at_ms=int(row["created_at_ms"]),
        updated_at_ms=int(row["updated_at_ms"]),
    )


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
