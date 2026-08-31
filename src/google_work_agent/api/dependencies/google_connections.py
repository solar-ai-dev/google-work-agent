"""Google-connection route dependency contract and provider."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from google_work_agent.api.dependencies.request_context import get_api_container
from google_work_agent.application.use_cases.connection.get_connection_status import (
    GetConnectionStatusHandler,
)
from google_work_agent.application.use_cases.connection.revoke_connection import (
    RevokeConnectionHandler,
)
from google_work_agent.application.use_cases.connection.start_authorization import (
    StartAuthorizationHandler,
)
from google_work_agent.ports.connector.oauth_credential_port import OAuthEnvironment


@dataclass(frozen=True, slots=True)
class GoogleRouteDependencies:
    api_contract_version: str
    start_authorization_handler: StartAuthorizationHandler | None
    get_connection_status_handler: GetConnectionStatusHandler | None
    revoke_connection_handler: RevokeConnectionHandler | None
    connector_id: str
    oauth_environment: OAuthEnvironment
    requested_scopes: tuple[str, ...]
    current_account_id: Callable[[], str | None]


def get_google_route_dependencies(request: Request) -> GoogleRouteDependencies:
    container = get_api_container(request)
    return GoogleRouteDependencies(
        api_contract_version=container.api_contract_version,
        start_authorization_handler=container.start_authorization_handler,
        get_connection_status_handler=container.get_connection_status_handler,
        revoke_connection_handler=container.revoke_connection_handler,
        connector_id=container.resource_connector_id,
        oauth_environment=container.oauth_environment,
        requested_scopes=container.oauth_requested_scopes,
        current_account_id=container.current_account_id_provider,
    )


GoogleRouteDependency = Annotated[
    GoogleRouteDependencies,
    Depends(get_google_route_dependencies),
]
