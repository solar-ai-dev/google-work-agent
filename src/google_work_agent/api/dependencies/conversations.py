"""Conversation route dependency contract and provider."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from google_work_agent.api.dependencies.request_context import get_api_container
from google_work_agent.application.use_cases.conversation.create_conversation import (
    CreateConversationHandler,
)
from google_work_agent.application.use_cases.conversation.get_conversation_history import (
    GetConversationHistoryHandler,
)
from google_work_agent.application.use_cases.conversation.list_conversations import (
    ListConversationsHandler,
)
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class ConversationRouteDependencies:
    api_contract_version: str
    unit_of_work_factory: Callable[[], UnitOfWork]
    create_conversation_handler: CreateConversationHandler
    list_conversations_handler: ListConversationsHandler
    get_conversation_history_handler: GetConversationHistoryHandler


def get_conversation_route_dependencies(request: Request) -> ConversationRouteDependencies:
    container = get_api_container(request)
    return ConversationRouteDependencies(
        api_contract_version=container.api_contract_version,
        unit_of_work_factory=lambda: container.unit_of_work_factory(),
        create_conversation_handler=container.create_conversation_handler,
        list_conversations_handler=container.list_conversations_handler,
        get_conversation_history_handler=container.get_conversation_history_handler,
    )


ConversationRouteDependency = Annotated[
    ConversationRouteDependencies,
    Depends(get_conversation_route_dependencies),
]
