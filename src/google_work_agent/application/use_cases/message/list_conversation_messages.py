"""List one Conversation's bounded Message timeline."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from google_work_agent.ports.persistence.unit_of_work import UnitOfWork

MAX_HISTORY_MESSAGES = 200


@dataclass(frozen=True, slots=True)
class ConversationMessageItem:
    id: str
    run_id: str | None
    role: str
    content: str
    created_at_ms: int


@dataclass(frozen=True, slots=True)
class ListConversationMessagesQuery:
    conversation_id: str


@dataclass(frozen=True, slots=True)
class ListConversationMessagesResult:
    items: tuple[ConversationMessageItem, ...]
    truncated: bool


class ListConversationMessagesHandler:
    def __init__(self, *, unit_of_work_factory: Callable[[], UnitOfWork]) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def __call__(self, query: ListConversationMessagesQuery) -> ListConversationMessagesResult:
        with self._unit_of_work_factory() as unit_of_work:
            records, next_cursor = unit_of_work.messages.list_by_conversation_keyset(
                conversation_id=query.conversation_id,
                cursor=None,
                page_size=MAX_HISTORY_MESSAGES,
            )
        return ListConversationMessagesResult(
            items=tuple(
                ConversationMessageItem(
                    id=record.id,
                    run_id=record.run_id,
                    role=record.role,
                    content=record.content,
                    created_at_ms=record.created_at_ms,
                )
                for record in reversed(records)
            ),
            truncated=next_cursor is not None,
        )
