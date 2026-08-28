"""Action route dependency contract and provider."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from google_work_agent.api.dependencies.request_context import get_api_container
from google_work_agent.application.calendar_conflicts import CalendarConflictGateway
from google_work_agent.application.task_duplicates import TaskListGateway
from google_work_agent.application.use_cases.run.resume_confirmation import ResumeTargetIssuer
from google_work_agent.application.use_cases.run.schedule_run_execution import (
    ScheduleRunExecutionCommand,
)
from google_work_agent.ports import ClockPort, SseEventBufferPort, UnitOfWork, UUIDPort
from google_work_agent.ports.system.contracts.workflow_handoff import RunExecutionAcceptedV1


@dataclass(frozen=True, slots=True)
class ActionRouteDependencies:
    api_contract_version: str
    unit_of_work_factory: Callable[[], UnitOfWork]
    schedule_run_execution: Callable[[ScheduleRunExecutionCommand], RunExecutionAcceptedV1]
    resume_target_registry: ResumeTargetIssuer
    event_publisher: Callable[[], SseEventBufferPort]
    clock: ClockPort
    id_generator: UUIDPort
    action_gateway: TaskListGateway | CalendarConflictGateway | None


def get_action_route_dependencies(request: Request) -> ActionRouteDependencies:
    container = get_api_container(request)
    if container.schedule_run_execution is None:
        raise RuntimeError("schedule_run_execution is not configured")
    if container.resume_target_registry is None:
        raise RuntimeError("resume-target registry is not configured")
    return ActionRouteDependencies(
        api_contract_version=container.api_contract_version,
        unit_of_work_factory=lambda: container.unit_of_work_factory(),
        schedule_run_execution=container.schedule_run_execution,
        resume_target_registry=container.resume_target_registry,
        event_publisher=lambda: container.event_publisher,
        clock=container.clock,
        id_generator=container.id_generator,
        action_gateway=container.action_gateway,
    )


ActionRouteDependency = Annotated[
    ActionRouteDependencies,
    Depends(get_action_route_dependencies),
]
