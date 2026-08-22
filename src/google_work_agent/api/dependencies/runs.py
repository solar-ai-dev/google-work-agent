"""Run route dependency contract and provider."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, cast

from fastapi import Depends, Request

from google_work_agent.api.dependencies.request_context import get_api_container
from google_work_agent.application.coordinator import LocalRunCoordinator
from google_work_agent.application.queries import QueryService
from google_work_agent.application.start_run import ResumeRunService, StartRunService
from google_work_agent.application.write_actions import (
    RequestRunCancellationService,
    ResolveMismatchRecoveryService,
)
from google_work_agent.ports import IdGenerator


@dataclass(frozen=True, slots=True)
class RunRouteDependencies:
    api_contract_version: str
    query_service: Callable[[], QueryService]
    start_run_service: Callable[[], StartRunService]
    cancel_run_service: Callable[[], RequestRunCancellationService]
    resume_run_service: Callable[[], ResumeRunService]
    resolve_recovery_service: Callable[[], ResolveMismatchRecoveryService]
    local_run_coordinator: LocalRunCoordinator
    id_generator: IdGenerator


def get_run_route_dependencies(request: Request) -> RunRouteDependencies:
    container = get_api_container(request)

    def resolve_recovery_service() -> ResolveMismatchRecoveryService:
        service = container.resolve_recovery_service
        if service is None:
            raise RuntimeError("resolve_recovery_service is not configured")
        return cast(ResolveMismatchRecoveryService, service)

    return RunRouteDependencies(
        api_contract_version=container.api_contract_version,
        query_service=lambda: container.query_service,
        start_run_service=lambda: container.start_run_service,
        cancel_run_service=lambda: container.cancel_run_service,
        resume_run_service=lambda: container.resume_run_service,
        resolve_recovery_service=resolve_recovery_service,
        local_run_coordinator=container.local_run_coordinator,
        id_generator=container.id_generator,
    )


RunRouteDependency = Annotated[
    RunRouteDependencies,
    Depends(get_run_route_dependencies),
]
