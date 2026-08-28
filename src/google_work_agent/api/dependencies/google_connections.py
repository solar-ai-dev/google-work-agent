"""Google-connection route dependency contract and provider."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from google_work_agent.api.dependencies.request_context import get_api_container


@dataclass(frozen=True, slots=True)
class GoogleRouteDependencies:
    api_contract_version: str
    start_authorization_handler: Callable[[], object | None]
    get_connection_status_handler: Callable[[], object | None]
    revoke_connection_handler: Callable[[], object | None]


def get_google_route_dependencies(request: Request) -> GoogleRouteDependencies:
    container = get_api_container(request)
    return GoogleRouteDependencies(
        api_contract_version=container.api_contract_version,
        start_authorization_handler=lambda: container.start_authorization_handler,
        get_connection_status_handler=lambda: container.get_connection_status_handler,
        revoke_connection_handler=lambda: container.revoke_connection_handler,
    )


GoogleRouteDependency = Annotated[
    GoogleRouteDependencies,
    Depends(get_google_route_dependencies),
]
