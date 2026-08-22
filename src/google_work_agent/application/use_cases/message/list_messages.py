"""Canonical bounded message-history query."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from google_work_agent.ports import QueryConnectionFactory

MAX_HISTORY_MESSAGES = 200


@dataclass(frozen=True, slots=True)
class MessageListItem:
    id: str
    run_id: str | None
    role: str
    content: str
    created_at_ms: int


@dataclass(frozen=True, slots=True)
class ListMessagesQuery:
    conversation_id: str


@dataclass(frozen=True, slots=True)
class ListMessagesResult:
    items: tuple[MessageListItem, ...]
    truncated: bool


class ListMessagesHandler:
    def __init__(self, *, database_path: Path, connection_factory: QueryConnectionFactory) -> None:
        self._database_path = database_path
        self._connection_factory = connection_factory

    def __call__(self, query: ListMessagesQuery) -> ListMessagesResult:
        with self._connection_factory(self._database_path) as connection:
            rows = connection.execute(
                """
                SELECT id, run_id, role, content, created_at_ms
                FROM messages
                WHERE conversation_id = ?
                ORDER BY created_at_ms DESC, id DESC
                LIMIT ?;
                """,
                (query.conversation_id, MAX_HISTORY_MESSAGES + 1),
            ).fetchall()
        truncated = len(rows) > MAX_HISTORY_MESSAGES
        retained = rows[:MAX_HISTORY_MESSAGES]
        return ListMessagesResult(
            items=tuple(
                MessageListItem(
                    id=str(row["id"]),
                    run_id=None if row["run_id"] is None else str(row["run_id"]),
                    role=str(row["role"]),
                    content=str(row["content"]),
                    created_at_ms=int(row["created_at_ms"]),
                )
                for row in reversed(retained)
            ),
            truncated=truncated,
        )
