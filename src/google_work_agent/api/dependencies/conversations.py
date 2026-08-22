"""Conversation route dependency contract and provider."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from google_work_agent.api.dependencies.request_context import get_api_container
from google_work_agent.application.queries import QueryService
from google_work_agent.application.start_run import CreateConversationService


@dataclass(frozen=True, slots=True)
class ConversationRouteDependencies:
    api_contract_version: str
    query_service: Callable[[], QueryService]
    create_conversation_service: Callable[[], CreateConversationService]


def get_conversation_route_dependencies(request: Request) -> ConversationRouteDependencies:
    container = get_api_container(request)
    return ConversationRouteDependencies(
        api_contract_version=container.api_contract_version,
        query_service=lambda: container.query_service,
        create_conversation_service=lambda: container.create_conversation_service,
    )


ConversationRouteDependency = Annotated[
    ConversationRouteDependencies,
    Depends(get_conversation_route_dependencies),
]
