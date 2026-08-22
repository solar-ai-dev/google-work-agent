"""Google-connection route dependency contract and provider."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from google_work_agent.api.dependencies.request_context import get_api_container
from google_work_agent.application.google_connection import (
    DisconnectGoogleService,
    GetGoogleConnectionService,
    StartGoogleOAuthService,
)


@dataclass(frozen=True, slots=True)
class GoogleRouteDependencies:
    api_contract_version: str
    start_google_oauth_service: Callable[[], StartGoogleOAuthService | None]
    get_google_connection_service: Callable[[], GetGoogleConnectionService | None]
    disconnect_google_service: Callable[[], DisconnectGoogleService | None]


def get_google_route_dependencies(request: Request) -> GoogleRouteDependencies:
    container = get_api_container(request)
    return GoogleRouteDependencies(
        api_contract_version=container.api_contract_version,
        start_google_oauth_service=lambda: container.start_google_oauth_service,
        get_google_connection_service=lambda: container.get_google_connection_service,
        disconnect_google_service=lambda: container.disconnect_google_service,
    )


GoogleRouteDependency = Annotated[
    GoogleRouteDependencies,
    Depends(get_google_route_dependencies),
]
