"""Action route dependency contract and provider."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from google_work_agent.api.dependencies.request_context import get_api_container
from google_work_agent.application.coordinator import LocalRunCoordinator
from google_work_agent.application.settings import GetSettingsService
from google_work_agent.application.start_run import (
    ModifyWriteActionService,
    RejectWriteActionService,
)
from google_work_agent.application.write_actions import (
    ApproveWriteActionService,
    PrepareWriteRetryService,
)
from google_work_agent.ports import ClockPort, UUIDPort, SseEventBufferPort, UnitOfWork


@dataclass(frozen=True, slots=True)
class ActionRouteDependencies:
    api_contract_version: str
    approve_action_service: Callable[[], ApproveWriteActionService]
    modify_action_service: Callable[[], ModifyWriteActionService]
    reject_action_service: Callable[[], RejectWriteActionService]
    prepare_retry_service: Callable[[], PrepareWriteRetryService]
    get_settings_service: Callable[[], GetSettingsService | None]
    unit_of_work_factory: Callable[[], UnitOfWork]
    local_run_coordinator: LocalRunCoordinator
    event_publisher: Callable[[], SseEventBufferPort]
    clock: ClockPort
    id_generator: UUIDPort


def get_action_route_dependencies(request: Request) -> ActionRouteDependencies:
    container = get_api_container(request)
    return ActionRouteDependencies(
        api_contract_version=container.api_contract_version,
        approve_action_service=lambda: container.approve_action_service,
        modify_action_service=lambda: container.modify_action_service,
        reject_action_service=lambda: container.reject_action_service,
        prepare_retry_service=lambda: container.prepare_retry_service,
        get_settings_service=lambda: container.get_settings_service,
        unit_of_work_factory=lambda: container.unit_of_work_factory(),
        local_run_coordinator=container.local_run_coordinator,
        event_publisher=lambda: container.event_publisher,
        clock=container.clock,
        id_generator=container.id_generator,
    )


ActionRouteDependency = Annotated[
    ActionRouteDependencies,
    Depends(get_action_route_dependencies),
]
