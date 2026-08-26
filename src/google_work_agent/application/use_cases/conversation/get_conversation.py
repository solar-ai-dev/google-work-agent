"""Canonical get-conversation query."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


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
    def __init__(self, *, unit_of_work_factory: Callable[[], UnitOfWork]) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def __call__(self, query: GetConversationQuery) -> GetConversationResult | None:
        with self._unit_of_work_factory() as unit_of_work:
            record = unit_of_work.conversations.get(query.conversation_id)
        if record is None:
            return None
        return GetConversationResult(
            id=record.id,
            account_id=record.account_id,
            title=record.title,
            created_at_ms=record.created_at_ms,
            updated_at_ms=record.updated_at_ms,
        )
