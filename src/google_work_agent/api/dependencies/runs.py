"""Run route dependency contract and provider."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Annotated, cast

from fastapi import Depends, Request

from google_work_agent.api.dependencies.request_context import get_api_container
from google_work_agent.application.coordinator import LocalRunCoordinator
from google_work_agent.application.queries import QueryService
from google_work_agent.ports import Clock, IdGenerator, UnitOfWork, WorkflowRuntime


@dataclass(frozen=True, slots=True)
class RunRouteDependencies:
    api_contract_version: str
    query_service: Callable[[], QueryService]
    unit_of_work_factory: Callable[[], UnitOfWork]
    reserve_queue_slot: Callable[[str], bool] | None
    release_queue_slot: Callable[[str], None] | None
    local_run_coordinator: LocalRunCoordinator
    workflow_runtime: WorkflowRuntime
    resolve_resume_authority: Callable[..., Mapping[str, object] | None]
    clock: Clock
    id_generator: IdGenerator


def get_run_route_dependencies(request: Request) -> RunRouteDependencies:
    container = get_api_container(request)
    start_run_service = container.start_run_service

    def resolve_resume_authority(
        *, run_id: str, resume_kind: str
    ) -> Mapping[str, object] | None:
        context = container.query_service.get_run_execution_context(run_id)
        if context is None:
            return None
        resolver = getattr(container.workflow_runtime, "resolve_resume_authority", None)
        if not callable(resolver):
            return None
        return cast(
            Mapping[str, object] | None,
            resolver(
                run_id=run_id,
                workflow_key=context.workflow_key,
                resume_kind=resume_kind,
            ),
        )

    return RunRouteDependencies(
        api_contract_version=container.api_contract_version,
        query_service=lambda: container.query_service,
        unit_of_work_factory=cast(Callable[[], UnitOfWork], container.unit_of_work_factory),
        reserve_queue_slot=getattr(start_run_service, "reserve_queue_slot", None),
        release_queue_slot=getattr(start_run_service, "release_queue_slot", None),
        local_run_coordinator=cast(LocalRunCoordinator, container.local_run_coordinator),
        workflow_runtime=container.workflow_runtime,
        resolve_resume_authority=resolve_resume_authority,
        clock=container.clock,
        id_generator=container.id_generator,
    )


RunRouteDependency = Annotated[
    RunRouteDependencies,
    Depends(get_run_route_dependencies),
]
