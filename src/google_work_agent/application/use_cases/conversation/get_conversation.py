"""Canonical get-conversation query."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from google_work_agent.ports import QueryConnectionFactory


@dataclass(frozen=True, slots=True)
class GetConversationQuery:
    conversation_id: str


@dataclass(frozen=True, slots=True)
class GetConversationResult:
    id: str
    account_id: str
    title: str
    updated_at_ms: int
    created_at_ms: int


class GetConversationHandler:
    def __init__(self, *, database_path: Path, connection_factory: QueryConnectionFactory) -> None:
        self._database_path = database_path
        self._connection_factory = connection_factory

    @classmethod
    def from_legacy_query_supplier(cls, supplier: Callable[[], object]) -> "GetConversationHandler":
        query = supplier()
        return cls(
            database_path=getattr(query, "_database_path"),
            connection_factory=getattr(query, "_connection_factory"),
        )

    def __call__(self, query: GetConversationQuery) -> GetConversationResult | None:
        with self._connection_factory(self._database_path) as connection:
            row = connection.execute(
                """
                SELECT id, account_id, title, created_at_ms, updated_at_ms
                FROM conversations WHERE id = ?;
                """,
                (query.conversation_id,),
            ).fetchone()
        if row is None:
            return None
        return GetConversationResult(
            id=str(row["id"]),
            account_id=str(row["account_id"]),
            title=str(row["title"]),
            created_at_ms=int(row["created_at_ms"]),
            updated_at_ms=int(row["updated_at_ms"]),
        )
