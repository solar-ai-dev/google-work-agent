"""Build the bounded, read-only Conversation history projection."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from google_work_agent.application.use_cases.conversation.get_conversation import (
    GetConversationResult,
)
from google_work_agent.application.use_cases.message.list_conversation_messages import (
    ConversationMessageItem,
    ListConversationMessagesHandler,
    ListConversationMessagesQuery,
)
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
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
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
        with self._unit_of_work_factory() as unit_of_work:
            run_records = unit_of_work.runs.list_by_conversation_bounded(
                query.conversation_id, limit=MAX_HISTORY_RUNS
            )
        runs = tuple(
            ConversationHistoryRunItem(
                run_id=record.id,
                status=record.status.value,
                started_at_ms=record.started_at_ms,
                finished_at_ms=record.finished_at_ms,
            )
            for record in reversed(run_records)
        )
        return GetConversationHistoryResult(
            conversation=conversation,
            messages=message_result.items,
            runs=runs,
            truncated=message_result.truncated,
        )
