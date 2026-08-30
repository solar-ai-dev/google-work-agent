"""Run route dependency contract and provider."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Annotated, cast

from fastapi import Depends, Request

from google_work_agent.api.dependencies.request_context import get_api_container
from google_work_agent.application.use_cases.resource.resolve_selection_handle import (
    ResolveSelectionHandle,
)
from google_work_agent.application.use_cases.run.continue_cancel_resolution import (
    ContinueCancelResolutionCommandV1,
    ContinueCancelResolutionResultV1,
)
from google_work_agent.application.use_cases.run.get_execution_context import (
    GetExecutionContextHandler,
    GetExecutionContextQuery,
)
from google_work_agent.application.use_cases.run.resume_confirmation import ResumeTargetIssuer
from google_work_agent.application.use_cases.run.schedule_run_execution import (
    ScheduleRunExecutionCommand,
)
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork
from google_work_agent.ports.system.clock_port import ClockPort
from google_work_agent.ports.system.contracts.workflow_binding import GraphProfileIdV1
from google_work_agent.ports.system.contracts.workflow_handoff import (
    RunExecutionAcceptedV1,
)
from google_work_agent.ports.system.operational_command_replay_port import (
    OperationalCommandReplayPort,
)
from google_work_agent.ports.system.settings_port import SettingsPort
from google_work_agent.ports.system.uuid_port import UUIDPort


@dataclass(frozen=True, slots=True)
class RunRouteDependencies:
    api_contract_version: str
    unit_of_work_factory: Callable[[], UnitOfWork]
    graph_profile: GraphProfileIdV1
    graph_version: str
    schedule_run_execution: Callable[[ScheduleRunExecutionCommand], RunExecutionAcceptedV1]
    workflow_runtime: object
    resolve_resume_authority: Callable[..., Mapping[str, object] | None]
    resolve_pending_confirmation: Callable[[str], Mapping[str, object] | None]
    resume_target_registry: ResumeTargetIssuer
    clock: ClockPort
    id_generator: UUIDPort
    settings: SettingsPort | None
    operational_command_replay: OperationalCommandReplayPort | None
    continue_cancel_resolution: Callable[
        [ContinueCancelResolutionCommandV1], ContinueCancelResolutionResultV1
    ] | None
    resolve_selection_handle: ResolveSelectionHandle
    resource_connector_id: str
    current_account_id: Callable[[], str | None]
    project_context_preview_handler: object | None
    adjust_context_handler: object | None
    project_recovery_options_handler: object | None
    project_error_actions_handler: object | None
    project_external_llm_transfer_scope_handler: object | None


def get_run_route_dependencies(request: Request) -> RunRouteDependencies:
    container = get_api_container(request)
    resolve_selection_handle = container.resolve_selection_handle
    if resolve_selection_handle is None:
        raise RuntimeError("selection-handle resolver is not configured")

    try:
        unit_of_work_factory = cast(Callable[[], UnitOfWork], container.unit_of_work_factory)
    except RuntimeError:

        def unit_of_work_factory() -> UnitOfWork:
            return cast(Callable[[], UnitOfWork], container.unit_of_work_factory)()

    def resolve_resume_authority(*, run_id: str, resume_kind: str) -> Mapping[str, object] | None:
        if resume_kind not in {"REAUTH_COMPLETED", "RECOVERY_RECHECK"}:
            return None
        context = GetExecutionContextHandler(unit_of_work_factory=unit_of_work_factory)(
            GetExecutionContextQuery(run_id=run_id)
        )
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
    if container.schedule_run_execution is None:
        raise RuntimeError("workflow execution scheduler is not configured")

    return RunRouteDependencies(
        api_contract_version=container.api_contract_version,
        unit_of_work_factory=unit_of_work_factory,
        graph_profile=container.graph_profile,
        graph_version=container.graph_version,
        schedule_run_execution=cast(
            Callable[[ScheduleRunExecutionCommand], RunExecutionAcceptedV1],
            container.schedule_run_execution,
        ),
        workflow_runtime=container.workflow_runtime,
        resolve_resume_authority=resolve_resume_authority,
        resolve_pending_confirmation=resolve_pending_confirmation,
        resume_target_registry=cast(ResumeTargetIssuer, container.resume_target_registry),
        clock=container.clock,
        id_generator=container.id_generator,
        settings=cast(SettingsPort | None, getattr(container, "settings_port", None)),
        operational_command_replay=cast(
            OperationalCommandReplayPort | None,
            getattr(container, "operational_command_replay", None),
        ),
        continue_cancel_resolution=cast(
            Callable[
                [ContinueCancelResolutionCommandV1], ContinueCancelResolutionResultV1
            ]
            | None,
            getattr(container, "continue_cancel_resolution_handler", None),
        ),
        resolve_selection_handle=resolve_selection_handle,
        resource_connector_id=container.resource_connector_id,
        current_account_id=container.current_account_id_provider,
        project_context_preview_handler=getattr(container, "project_context_preview_handler", None),
        adjust_context_handler=getattr(container, "adjust_context_handler", None),
        project_recovery_options_handler=getattr(
            container, "project_recovery_options_handler", None
        ),
        project_error_actions_handler=getattr(container, "project_error_actions_handler", None),
        project_external_llm_transfer_scope_handler=(
            getattr(container, "project_external_llm_transfer_scope_handler", None)
        ),
    )


RunRouteDependency = Annotated[
    RunRouteDependencies,
    Depends(get_run_route_dependencies),
]
