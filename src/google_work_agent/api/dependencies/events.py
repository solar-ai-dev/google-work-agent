"""Event route dependency contract and provider."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from google_work_agent.api.dependencies.request_context import get_api_container
from google_work_agent.application.queries import QueryService
from google_work_agent.ports import Clock, RunEventPublisher


@dataclass(frozen=True, slots=True)
class EventRouteDependencies:
    api_contract_version: str
    query_service: Callable[[], QueryService]
    event_publisher: Callable[[], RunEventPublisher]
    clock: Clock


def get_event_route_dependencies(request: Request) -> EventRouteDependencies:
    container = get_api_container(request)
    return EventRouteDependencies(
        api_contract_version=container.api_contract_version,
        query_service=lambda: container.query_service,
        event_publisher=lambda: container.event_publisher,
        clock=container.clock,
    )


EventRouteDependency = Annotated[
    EventRouteDependencies,
    Depends(get_event_route_dependencies),
]
