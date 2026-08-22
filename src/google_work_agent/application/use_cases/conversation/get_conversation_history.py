"""Canonical conversation timeline assembly."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from google_work_agent.application.use_cases.conversation.get_conversation import (
    GetConversationHandler,
    GetConversationQuery,
    GetConversationResult,
)
from google_work_agent.application.use_cases.message.list_messages import (
    ListMessagesHandler,
    ListMessagesQuery,
    MessageListItem,
)
from google_work_agent.ports import QueryConnectionFactory

MAX_HISTORY_RUNS = 200


@dataclass(frozen=True, slots=True)
class ConversationHistoryRunItem:
    run_id: str
    status: str
    started_at_ms: int
    finished_at_ms: int | None


@dataclass(frozen=True, slots=True)
class GetConversationHistoryQuery:
    conversation_id: str


@dataclass(frozen=True, slots=True)
class GetConversationHistoryResult:
    conversation: GetConversationResult
    messages: tuple[MessageListItem, ...]
    runs: tuple[ConversationHistoryRunItem, ...]
    truncated: bool


class GetConversationHistoryHandler:
    def __init__(self, *, database_path: Path, connection_factory: QueryConnectionFactory) -> None:
        self._database_path = database_path
        self._connection_factory = connection_factory
        self._get_conversation = GetConversationHandler(
            database_path=database_path, connection_factory=connection_factory
        )
        self._list_messages = ListMessagesHandler(
            database_path=database_path, connection_factory=connection_factory
        )

    @classmethod
    def from_legacy_query_supplier(
        cls, supplier: Callable[[], object]
    ) -> "GetConversationHistoryHandler":
        query = supplier()
        return cls(
            database_path=getattr(query, "_database_path"),
            connection_factory=getattr(query, "_connection_factory"),
        )

    def __call__(self, query: GetConversationHistoryQuery) -> GetConversationHistoryResult | None:
        conversation = self._get_conversation(
            GetConversationQuery(conversation_id=query.conversation_id)
        )
        if conversation is None:
            return None
        message_result = self._list_messages(
            ListMessagesQuery(conversation_id=query.conversation_id)
        )
        with self._connection_factory(self._database_path) as connection:
            run_rows = connection.execute(
                """
                SELECT id, status, started_at_ms, finished_at_ms
                FROM runs
                WHERE conversation_id = ?
                ORDER BY started_at_ms DESC, id DESC
                LIMIT ?;
                """,
                (query.conversation_id, MAX_HISTORY_RUNS),
            ).fetchall()
        runs = tuple(
            ConversationHistoryRunItem(
                run_id=str(row["id"]),
                status=str(row["status"]),
                started_at_ms=int(row["started_at_ms"]),
                finished_at_ms=(
                    None if row["finished_at_ms"] is None else int(row["finished_at_ms"])
                ),
            )
            for row in reversed(run_rows)
        )
        return GetConversationHistoryResult(
            conversation=conversation,
            messages=message_result.items,
            runs=runs,
            truncated=message_result.truncated,
        )
