"""Local-session route dependency contract and provider."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from google_work_agent.api.dependencies.request_context import get_api_container
from google_work_agent.api.security.bootstrap import BootstrapGrantStore
from google_work_agent.api.security.sessions import LocalSessionManager
from google_work_agent.ports import ClockPort


@dataclass(frozen=True, slots=True)
class SessionRouteDependencies:
    service_instance_id: str
    api_contract_version: str
    clock: ClockPort
    bootstrap_grant_store: BootstrapGrantStore | None
    local_session_manager: LocalSessionManager | None


def get_session_route_dependencies(request: Request) -> SessionRouteDependencies:
    container = get_api_container(request)
    return SessionRouteDependencies(
        service_instance_id=container.service_instance_id,
        api_contract_version=container.api_contract_version,
        clock=container.clock,
        bootstrap_grant_store=container.bootstrap_grant_store,
        local_session_manager=container.local_session_manager,
    )


SessionRouteDependency = Annotated[
    SessionRouteDependencies,
    Depends(get_session_route_dependencies),
]
