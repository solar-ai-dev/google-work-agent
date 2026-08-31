"""Run route dependency contract and provider."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, cast

from fastapi import Depends, Request

from google_work_agent.api.dependencies.request_context import get_api_container
from google_work_agent.application.use_cases.recovery.resolve_recovery import (
    ResolveRecoveryHandler,
)
from google_work_agent.application.use_cases.resource.resolve_selection_handle import (
    ResolveSelectionHandle,
)
from google_work_agent.application.use_cases.run.confirm_run import ConfirmRunHandler
from google_work_agent.application.use_cases.run.get_run_snapshot import GetRunSnapshotHandler
from google_work_agent.application.use_cases.run.request_cancel import RequestCancelHandler
from google_work_agent.application.use_cases.run.resume_after_reauth import (
    ResumeAfterReauthHandler,
)
from google_work_agent.application.use_cases.run.resume_safe_checkpoint import (
    ResumeSafeCheckpointHandler,
)
from google_work_agent.application.use_cases.run.schedule_run_execution import (
    ScheduleRunExecutionCommand,
)
from google_work_agent.application.use_cases.run.start_run import StartRunHandler
from google_work_agent.application.use_cases.sse_event.list_run_events import ListRunEventsHandler
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork
from google_work_agent.ports.system.contracts.workflow_binding import GraphProfileIdV1
from google_work_agent.ports.system.contracts.workflow_handoff import (
    RunExecutionAcceptedV1,
)
from google_work_agent.ports.system.sse_event_buffer_port import SseEventBufferPort


@dataclass(frozen=True, slots=True)
class RunRouteDependencies:
    api_contract_version: str
    service_instance_id: str
    read_unit_of_work_factory: Callable[[], UnitOfWork]
    graph_profile: GraphProfileIdV1
    graph_version: str
    schedule_run_execution: Callable[[ScheduleRunExecutionCommand], RunExecutionAcceptedV1]
    resolve_selection_handle: ResolveSelectionHandle
    resource_connector_id: str
    current_account_id: Callable[[], str | None]
    project_context_preview_handler: object | None
    adjust_context_handler: object | None
    request_cancel_handler: RequestCancelHandler | None
    resume_safe_checkpoint_handler: ResumeSafeCheckpointHandler | None
    resume_after_reauth_handler: ResumeAfterReauthHandler | None
    resolve_recovery_handler: ResolveRecoveryHandler | None
    confirm_run_handler: ConfirmRunHandler | None
    project_recovery_options_handler: object | None
    project_error_actions_handler: object | None
    project_external_llm_transfer_scope_handler: object | None
    start_run_handler: StartRunHandler | None
    get_run_snapshot_handler: GetRunSnapshotHandler | None
    list_run_events_handler: ListRunEventsHandler | None
    event_buffer: SseEventBufferPort | None


def get_run_route_dependencies(request: Request) -> RunRouteDependencies:
    container = get_api_container(request)
    resolve_selection_handle = container.resolve_selection_handle
    if resolve_selection_handle is None:
        raise RuntimeError("selection-handle resolver is not configured")

    read_unit_of_work_factory = cast(
        Callable[[], UnitOfWork],
        getattr(container, "read_unit_of_work_factory", None) or container.unit_of_work_factory,
    )
    if container.schedule_run_execution is None:
        raise RuntimeError("workflow execution scheduler is not configured")

    return RunRouteDependencies(
        api_contract_version=container.api_contract_version,
        service_instance_id=container.service_instance_id,
        read_unit_of_work_factory=read_unit_of_work_factory,
        graph_profile=container.graph_profile,
        graph_version=container.graph_version,
        schedule_run_execution=cast(
            Callable[[ScheduleRunExecutionCommand], RunExecutionAcceptedV1],
            container.schedule_run_execution,
        ),
        resolve_selection_handle=resolve_selection_handle,
        resource_connector_id=container.resource_connector_id,
        current_account_id=container.current_account_id_provider,
        project_context_preview_handler=getattr(container, "project_context_preview_handler", None),
        adjust_context_handler=getattr(container, "adjust_context_handler", None),
        request_cancel_handler=cast(
            RequestCancelHandler | None, getattr(container, "request_cancel_handler", None)
        ),
        resume_safe_checkpoint_handler=cast(
            ResumeSafeCheckpointHandler | None,
            getattr(container, "resume_safe_checkpoint_handler", None),
        ),
        resume_after_reauth_handler=cast(
            ResumeAfterReauthHandler | None,
            getattr(container, "resume_after_reauth_handler", None),
        ),
        resolve_recovery_handler=cast(
            ResolveRecoveryHandler | None,
            getattr(container, "resolve_recovery_handler", None),
        ),
        confirm_run_handler=cast(
            ConfirmRunHandler | None, getattr(container, "confirm_run_handler", None)
        ),
        project_recovery_options_handler=getattr(
            container, "project_recovery_options_handler", None
        ),
        project_error_actions_handler=getattr(container, "project_error_actions_handler", None),
        project_external_llm_transfer_scope_handler=(
            getattr(container, "project_external_llm_transfer_scope_handler", None)
        ),
        start_run_handler=cast(
            StartRunHandler | None, getattr(container, "start_run_handler", None)
        ),
        get_run_snapshot_handler=cast(
            GetRunSnapshotHandler | None, getattr(container, "get_run_snapshot_handler", None)
        ),
        list_run_events_handler=cast(
            ListRunEventsHandler | None, getattr(container, "list_run_events_handler", None)
        ),
        event_buffer=cast(SseEventBufferPort | None, getattr(container, "event_publisher", None)),
    )


RunRouteDependency = Annotated[
    RunRouteDependencies,
    Depends(get_run_route_dependencies),
]


@dataclass(frozen=True, slots=True)
class RunEventRouteDependencies:
    api_contract_version: str
    list_run_events_handler: ListRunEventsHandler | None
    event_buffer: SseEventBufferPort | None


def get_run_event_route_dependencies(request: Request) -> RunEventRouteDependencies:
    container = get_api_container(request)
    return RunEventRouteDependencies(
        api_contract_version=container.api_contract_version,
        list_run_events_handler=cast(
            ListRunEventsHandler | None, getattr(container, "list_run_events_handler", None)
        ),
        event_buffer=cast(SseEventBufferPort | None, getattr(container, "event_publisher", None)),
    )


RunEventRouteDependency = Annotated[
    RunEventRouteDependencies,
    Depends(get_run_event_route_dependencies),
]
