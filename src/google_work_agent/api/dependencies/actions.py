"""Action route dependency contract and provider."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from google_work_agent.api.dependencies.request_context import get_api_container
from google_work_agent.application.use_cases.action.approve_action import ApproveActionHandler
from google_work_agent.application.use_cases.action.modify_action import ModifyActionHandler
from google_work_agent.application.use_cases.action.prepare_write_retry import (
    PrepareWriteRetryHandler,
)
from google_work_agent.application.use_cases.action.reject_action import RejectActionHandler


@dataclass(frozen=True, slots=True)
class ActionRouteDependencies:
    api_contract_version: str
    approve_action_handler: ApproveActionHandler
    modify_action_handler: ModifyActionHandler
    reject_action_handler: RejectActionHandler
    prepare_write_retry_handler: PrepareWriteRetryHandler


def get_action_route_dependencies(request: Request) -> ActionRouteDependencies:
    container = get_api_container(request)
    approve = container.approve_action_handler
    modify = container.modify_action_handler
    reject = container.reject_action_handler
    prepare_retry = container.prepare_write_retry_handler
    if approve is None or modify is None or reject is None or prepare_retry is None:
        raise RuntimeError("action command handlers are not configured")
    return ActionRouteDependencies(
        api_contract_version=container.api_contract_version,
        approve_action_handler=approve,
        modify_action_handler=modify,
        reject_action_handler=reject,
        prepare_write_retry_handler=prepare_retry,
    )


ActionRouteDependency = Annotated[
    ActionRouteDependencies,
    Depends(get_action_route_dependencies),
]
