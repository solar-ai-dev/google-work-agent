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
HISTORY_RUN_SCAN_PAGE_SIZE = 200
HISTORY_RUN_SCAN_MULTIPLIER = 10


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
            run_ids = _recent_run_ids(
                unit_of_work,
                conversation_id=query.conversation_id,
                limit=self._history_run_limit,
            )
            open_run = unit_of_work.runs.find_open_by_conversation(query.conversation_id)
            if open_run is not None and open_run.id not in run_ids:
                run_ids.insert(0, open_run.id)
                del run_ids[self._history_run_limit :]
            run_records = tuple(
                run for run_id in run_ids if (run := unit_of_work.runs.get(run_id)) is not None
            )
        run_records = tuple(sorted(run_records, key=lambda item: (item.started_at_ms, item.id)))
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


def _recent_run_ids(
    unit_of_work: UnitOfWork,
    *,
    conversation_id: str,
    limit: int,
) -> list[str]:
    """Derive bounded recent Run identities through the exact Message keyset surface."""

    run_ids: list[str] = []
    cursor: str | None = None
    scanned = 0
    scan_limit = max(HISTORY_RUN_SCAN_PAGE_SIZE, limit * HISTORY_RUN_SCAN_MULTIPLIER)
    while len(run_ids) < limit and scanned < scan_limit:
        page_size = min(HISTORY_RUN_SCAN_PAGE_SIZE, scan_limit - scanned)
        messages, next_cursor = unit_of_work.messages.list_by_conversation_keyset(
            conversation_id=conversation_id,
            cursor=cursor,
            page_size=page_size,
        )
        scanned += len(messages)
        for message in messages:
            if message.run_id is not None and message.run_id not in run_ids:
                run_ids.append(message.run_id)
                if len(run_ids) >= limit:
                    break
        if next_cursor is None:
            break
        cursor = next_cursor
    return run_ids
