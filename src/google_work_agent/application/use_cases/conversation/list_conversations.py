"""List Conversations application query."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from google_work_agent.ports.persistence.unit_of_work import UnitOfWork

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
    def __init__(self, *, unit_of_work_factory: Callable[[], UnitOfWork]) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def __call__(self, query: ListConversationsQuery) -> ListConversationsResult:
        if not 1 <= query.page_size <= MAX_PAGE_SIZE:
            raise ValueError(f"page_size must be between 1 and {MAX_PAGE_SIZE}")
        with self._unit_of_work_factory() as unit_of_work:
            records, next_cursor = unit_of_work.conversations.list_keyset(
                account_id=query.account_id,
                cursor=query.cursor,
                page_size=query.page_size,
            )
        return ListConversationsResult(
            items=tuple(
                ConversationListItem(
                    id=record.id,
                    account_id=record.account_id,
                    title=record.title,
                    created_at_ms=record.created_at_ms,
                    updated_at_ms=record.updated_at_ms,
                )
                for record in records
            ),
            next_cursor=next_cursor,
        )
