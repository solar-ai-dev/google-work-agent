"""Resource route dependency contract and provider."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from google_work_agent.api.dependencies.request_context import get_api_container
from google_work_agent.application.resource_queries import ResourceQueryService


@dataclass(frozen=True, slots=True)
class ResourceRouteDependencies:
    api_contract_version: str
    resource_query_service: Callable[[], ResourceQueryService | None]


def get_resource_route_dependencies(request: Request) -> ResourceRouteDependencies:
    container = get_api_container(request)
    return ResourceRouteDependencies(
        api_contract_version=container.api_contract_version,
        resource_query_service=lambda: container.resource_query_service,
    )


ResourceRouteDependency = Annotated[
    ResourceRouteDependencies,
    Depends(get_resource_route_dependencies),
]
