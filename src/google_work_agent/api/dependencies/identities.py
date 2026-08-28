"""Identity route dependency contract and provider."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from google_work_agent.api.dependencies.request_context import get_api_container


@dataclass(frozen=True, slots=True)
class IdentityRouteDependencies:
    api_contract_version: str
    get_connection_status_handler: object | None


def get_identity_route_dependencies(request: Request) -> IdentityRouteDependencies:
    container = get_api_container(request)
    return IdentityRouteDependencies(
        api_contract_version=container.api_contract_version,
        get_connection_status_handler=container.get_connection_status_handler,
    )


IdentityRouteDependency = Annotated[
    IdentityRouteDependencies,
    Depends(get_identity_route_dependencies),
]
