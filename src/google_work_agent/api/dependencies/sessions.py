"""Local-session route dependency contract and provider."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from google_work_agent.api.dependencies.request_context import get_api_container
from google_work_agent.api.security.bootstrap_session import BootstrapSessionService
from google_work_agent.ports.system.clock_port import ClockPort


@dataclass(frozen=True, slots=True)
class SessionRouteDependencies:
    service_instance_id: str
    api_contract_version: str
    clock: ClockPort
    bootstrap_session_service: BootstrapSessionService | None


def get_session_route_dependencies(request: Request) -> SessionRouteDependencies:
    container = get_api_container(request)
    store = container.bootstrap_grant_store
    session_manager = container.local_session_manager
    service = (
        None
        if store is None or session_manager is None
        else BootstrapSessionService(
            grant_store=store,
            session_manager=session_manager,
            service_instance_id=container.service_instance_id,
            api_contract_version=container.api_contract_version,
        )
    )
    return SessionRouteDependencies(
        service_instance_id=container.service_instance_id,
        api_contract_version=container.api_contract_version,
        clock=container.clock,
        bootstrap_session_service=service,
    )


SessionRouteDependency = Annotated[
    SessionRouteDependencies,
    Depends(get_session_route_dependencies),
]
