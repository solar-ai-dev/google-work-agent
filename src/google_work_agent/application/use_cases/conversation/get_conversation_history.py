"""Build the bounded, read-only Conversation history projection."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from google_work_agent.application.use_cases.conversation.get_conversation import (
    GetConversationResult,
)
from google_work_agent.application.use_cases.message.list_conversation_messages import (
    ConversationMessageItem,
    ListConversationMessagesHandler,
    ListConversationMessagesQuery,
)
from google_work_agent.ports import QueryConnectionFactory
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork

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
    messages: tuple[ConversationMessageItem, ...]
    runs: tuple[ConversationHistoryRunItem, ...]
    truncated: bool


class GetConversationHistoryHandler:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        database_path: Path,
        connection_factory: QueryConnectionFactory,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._database_path = database_path
        self._connection_factory = connection_factory
        self._list_messages = ListConversationMessagesHandler(
            unit_of_work_factory=unit_of_work_factory
        )

    def __call__(self, query: GetConversationHistoryQuery) -> GetConversationHistoryResult | None:
        with self._unit_of_work_factory() as unit_of_work:
            record = unit_of_work.conversations.get(query.conversation_id)
        if record is None:
            return None
        conversation = GetConversationResult(
            id=record.id,
            account_id=record.account_id,
            title=record.title,
            created_at_ms=record.created_at_ms,
            updated_at_ms=record.updated_at_ms,
        )
        message_result = self._list_messages(
            ListConversationMessagesQuery(conversation_id=query.conversation_id)
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
