"""SQLite Conversation repository adapter."""

from __future__ import annotations

import sqlite3

from google_work_agent.domain.conversation.model import Conversation as ConversationRecord


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
    ) -> tuple[tuple[ConversationRecord, ...], str | None]:
        predicate = "WHERE account_id = ?"
        params: list[object] = [account_id]
        if cursor is not None:
            raw_time, conversation_id = cursor.split(":", 1)
            updated_at_ms = int(raw_time)
            predicate += " AND (updated_at_ms < ? OR (updated_at_ms = ? AND id < ?))"
            params.extend([updated_at_ms, updated_at_ms, conversation_id])
        params.append(page_size + 1)
        rows = self._connection.execute(
            f"""
            SELECT id, account_id, title, created_at_ms, updated_at_ms
            FROM conversations
            {predicate}
            ORDER BY updated_at_ms DESC, id DESC
            LIMIT ?;
            """,
            tuple(params),
        ).fetchall()
        items = tuple(_record_from_row(row) for row in rows[:page_size])
        next_cursor = None
        if len(rows) > page_size and items:
            last = items[-1]
            next_cursor = f"{last.updated_at_ms}:{last.id}"
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
