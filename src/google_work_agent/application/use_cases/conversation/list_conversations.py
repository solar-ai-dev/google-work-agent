"""Canonical list-conversations query."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from google_work_agent.ports import QueryConnectionFactory

MAX_PAGE_SIZE = 100


@dataclass(frozen=True, slots=True)
class ConversationListItem:
    id: str
    account_id: str
    title: str
    updated_at_ms: int
    created_at_ms: int


@dataclass(frozen=True, slots=True)
class ListConversationsQuery:
    account_id: str
    cursor: str | None
    page_size: int


@dataclass(frozen=True, slots=True)
class ListConversationsResult:
    items: tuple[ConversationListItem, ...]
    next_cursor: str | None


class ListConversationsHandler:
    def __init__(self, *, database_path: Path, connection_factory: QueryConnectionFactory) -> None:
        self._database_path = database_path
        self._connection_factory = connection_factory

    @classmethod
    def from_legacy_query_supplier(cls, supplier: Callable[[], object]) -> "ListConversationsHandler":
        query = supplier()
        return cls(
            database_path=getattr(query, "_database_path"),
            connection_factory=getattr(query, "_connection_factory"),
        )

    def __call__(self, query: ListConversationsQuery) -> ListConversationsResult:
        if not 1 <= query.page_size <= MAX_PAGE_SIZE:
            raise ValueError(f"page_size must be between 1 and {MAX_PAGE_SIZE}")
        predicate = "WHERE account_id = ?"
        params: list[object] = [query.account_id]
        if query.cursor is not None:
            raw_time, conversation_id = query.cursor.split(":", 1)
            updated_at_ms = int(raw_time)
            predicate += " AND (updated_at_ms < ? OR (updated_at_ms = ? AND id < ?))"
            params.extend([updated_at_ms, updated_at_ms, conversation_id])
        params.append(query.page_size + 1)
        with self._connection_factory(self._database_path) as connection:
            rows = connection.execute(
                f"""
                SELECT id, account_id, title, created_at_ms, updated_at_ms
                FROM conversations
                {predicate}
                ORDER BY updated_at_ms DESC, id DESC
                LIMIT ?;
                """,
                tuple(params),
            ).fetchall()
        items = tuple(
            ConversationListItem(
                id=str(row["id"]),
                account_id=str(row["account_id"]),
                title=str(row["title"]),
                created_at_ms=int(row["created_at_ms"]),
                updated_at_ms=int(row["updated_at_ms"]),
            )
            for row in rows[: query.page_size]
        )
        next_cursor = None
        if len(rows) > query.page_size and items:
            last = items[-1]
            next_cursor = f"{last.updated_at_ms}:{last.id}"
        return ListConversationsResult(items=items, next_cursor=next_cursor)
