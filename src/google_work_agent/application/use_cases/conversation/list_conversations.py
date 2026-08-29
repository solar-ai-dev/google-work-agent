"""List Conversations application query."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from google_work_agent.ports.persistence.unit_of_work import UnitOfWork

MAX_PAGE_SIZE = 50
MAX_SEARCH_CHARS = 256


@dataclass(frozen=True, slots=True)
class ConversationListItem:
    schema_version: int
    conversation_id: str
    title: str | None
    latest_message_at_ms: int | None
    open_run_id: str | None


@dataclass(frozen=True, slots=True)
class ListConversationsQuery:
    account_id: str
    cursor: str | None = None
    page_size: int = 50
    search: str | None = None


@dataclass(frozen=True, slots=True)
class ListConversationsResult:
    items: tuple[ConversationListItem, ...]
    next_cursor: str | None


class ListConversationsHandler:
    def __init__(self, *, unit_of_work_factory: Callable[[], UnitOfWork]) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def __call__(self, query: ListConversationsQuery) -> ListConversationsResult:
        if not 1 <= query.page_size <= MAX_PAGE_SIZE:
            raise ValueError(f"page_size must be between 1 and {MAX_PAGE_SIZE}")
        search = _normalize_search(query.search)
        with self._unit_of_work_factory() as unit_of_work:
            records, next_cursor = unit_of_work.conversations.list_keyset(
                account_id=query.account_id,
                cursor=query.cursor,
                page_size=query.page_size,
                search=search,
            )
        return ListConversationsResult(
            items=tuple(
                ConversationListItem(
                    schema_version=1,
                    conversation_id=record.conversation.id,
                    title=record.conversation.title,
                    latest_message_at_ms=record.latest_message_at_ms,
                    open_run_id=record.open_run_id,
                )
                for record in records
            ),
            next_cursor=next_cursor,
        )


def _normalize_search(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split())
    if not normalized:
        return None
    if len(normalized) > MAX_SEARCH_CHARS:
        raise ValueError(f"search must be at most {MAX_SEARCH_CHARS} characters")
    return normalized
