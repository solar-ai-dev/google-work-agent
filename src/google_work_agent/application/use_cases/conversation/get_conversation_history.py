"""Build the bounded, read-only Conversation history projection."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from google_work_agent.application.use_cases.conversation.list_conversations import (
    ConversationListItem,
)
from google_work_agent.application.use_cases.message.list_conversation_messages import (
    ConversationMessageItem,
    ListConversationMessagesHandler,
    ListConversationMessagesQuery,
)
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork

DEFAULT_HISTORY_MESSAGE_LIMIT = 200
DEFAULT_HISTORY_RUN_LIMIT = 200


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
    conversation: ConversationListItem
    messages: tuple[ConversationMessageItem, ...]
    runs: tuple[ConversationHistoryRunItem, ...]
    truncated: bool


class GetConversationHistoryHandler:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        history_message_limit: int = DEFAULT_HISTORY_MESSAGE_LIMIT,
        history_run_limit: int = DEFAULT_HISTORY_RUN_LIMIT,
    ) -> None:
        if history_message_limit < 1 or history_run_limit < 1:
            raise ValueError("history limits must be positive")
        self._unit_of_work_factory = unit_of_work_factory
        self._history_run_limit = history_run_limit
        self._list_messages = ListConversationMessagesHandler(
            unit_of_work_factory=unit_of_work_factory,
            page_size=history_message_limit,
        )

    def __call__(self, query: GetConversationHistoryQuery) -> GetConversationHistoryResult | None:
        with self._unit_of_work_factory() as unit_of_work:
            conversation_record = unit_of_work.conversations.get(query.conversation_id)
        if conversation_record is None:
            return None
        message_result = self._list_messages(
            ListConversationMessagesQuery(conversation_id=query.conversation_id)
        )
        with self._unit_of_work_factory() as unit_of_work:
            run_records = unit_of_work.runs.list_for_conversation_bounded(
                query.conversation_id,
                limit=self._history_run_limit,
            )
        runs = tuple(
            ConversationHistoryRunItem(
                run_id=run_record.id,
                status=run_record.status.value,
                started_at_ms=run_record.started_at_ms,
                finished_at_ms=run_record.finished_at_ms,
            )
            for run_record in run_records
        )
        conversation = ConversationListItem(
            schema_version=1,
            conversation_id=conversation_record.id,
            title=conversation_record.title,
            latest_message_at_ms=(
                None if not message_result.items else message_result.items[-1].created_at_ms
            ),
            open_run_id=next(
                (item.run_id for item in reversed(runs) if item.finished_at_ms is None),
                None,
            ),
        )
        return GetConversationHistoryResult(
            conversation=conversation,
            messages=message_result.items,
            runs=runs,
            truncated=message_result.truncated,
        )
