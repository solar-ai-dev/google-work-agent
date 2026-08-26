"""Run route dependency contract and provider."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Annotated, cast

from fastapi import Depends, Request

from google_work_agent.api.dependencies.request_context import get_api_container
from google_work_agent.application.coordinator import LocalRunCoordinator
from google_work_agent.application.queries import QueryService
from google_work_agent.application.use_cases.resource.resolve_selection_handle import (
    ResolveSelectionHandle,
)
from google_work_agent.application.use_cases.run.schedule_run_execution import (
    ScheduleRunExecutionCommand,
)
from google_work_agent.ports import Clock, IdGenerator, UnitOfWork, WorkflowRuntime
from google_work_agent.ports.system.contracts.workflow_binding import GraphProfileIdV1
from google_work_agent.ports.system.contracts.workflow_handoff import (
    RunExecutionAcceptedV1,
)


@dataclass(frozen=True, slots=True)
class RunRouteDependencies:
    api_contract_version: str
    query_service: Callable[[], QueryService]
    unit_of_work_factory: Callable[[], UnitOfWork]
    graph_profile: GraphProfileIdV1
    graph_version: str
    schedule_run_execution: Callable[[ScheduleRunExecutionCommand], RunExecutionAcceptedV1]
    local_run_coordinator: LocalRunCoordinator
    workflow_runtime: WorkflowRuntime
    resolve_resume_authority: Callable[..., Mapping[str, object] | None]
    resolve_pending_confirmation: Callable[[str], Mapping[str, object] | None]
    resume_target_registry: object
    clock: Clock
    id_generator: IdGenerator
    resolve_selection_handle: ResolveSelectionHandle
    resource_connector_id: str
    current_account_id: Callable[[], str | None]


def get_run_route_dependencies(request: Request) -> RunRouteDependencies:
    container = get_api_container(request)
    resolve_selection_handle = container.resolve_selection_handle
    if resolve_selection_handle is None:
        raise RuntimeError("selection-handle resolver is not configured")

    def resolve_resume_authority(*, run_id: str, resume_kind: str) -> Mapping[str, object] | None:
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

    def resolve_pending_confirmation(run_id: str) -> Mapping[str, object] | None:
        resolver = getattr(container.workflow_runtime, "resolve_pending_confirmation", None)
        if not callable(resolver):
            return None
        return cast(Mapping[str, object] | None, resolver(run_id))

    if container.resume_target_registry is None:
        raise RuntimeError("resume-target registry is not configured")

    return RunRouteDependencies(
        api_contract_version=container.api_contract_version,
        query_service=lambda: container.query_service,
        unit_of_work_factory=cast(Callable[[], UnitOfWork], container.unit_of_work_factory),
        graph_profile=container.graph_profile,
        graph_version=container.graph_version,
        schedule_run_execution=container.schedule_run_execution,
        local_run_coordinator=cast(LocalRunCoordinator, container.local_run_coordinator),
        workflow_runtime=container.workflow_runtime,
        resolve_resume_authority=resolve_resume_authority,
        resolve_pending_confirmation=resolve_pending_confirmation,
        resume_target_registry=container.resume_target_registry,
        clock=container.clock,
        id_generator=container.id_generator,
        resolve_selection_handle=resolve_selection_handle,
        resource_connector_id=container.resource_connector_id,
        current_account_id=lambda: _current_account_id(container.query_service),
    )


def _current_account_id(query_service: object) -> str | None:
    getter = getattr(query_service, "get_current_google_account", None)
    if getter is None:
        return None
    account = getter()
    return None if account is None else str(account.account_id)


RunRouteDependency = Annotated[
    RunRouteDependencies,
    Depends(get_run_route_dependencies),
]
