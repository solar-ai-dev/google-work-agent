"""Identity route dependency contract and provider."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from google_work_agent.api.dependencies.request_context import get_api_container
from google_work_agent.application.queries import QueryService


@dataclass(frozen=True, slots=True)
class IdentityRouteDependencies:
    api_contract_version: str
    query_service: Callable[[], QueryService]


def get_identity_route_dependencies(request: Request) -> IdentityRouteDependencies:
    container = get_api_container(request)
    return IdentityRouteDependencies(
        api_contract_version=container.api_contract_version,
        query_service=lambda: container.query_service,
    )


IdentityRouteDependency = Annotated[
    IdentityRouteDependencies,
    Depends(get_identity_route_dependencies),
]
