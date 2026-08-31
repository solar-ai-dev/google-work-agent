"""Runtime-summary route dependency contract and provider."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from google_work_agent.api.dependencies.request_context import get_api_container
from google_work_agent.application.use_cases.runtime_mode.update_runtime_mode import (
    UpdateRuntimeModeHandler,
)
from google_work_agent.application.use_cases.runtime_status.get_runtime_status import (
    GetRuntimeStatusHandler,
)


@dataclass(frozen=True, slots=True)
class RuntimeRouteDependencies:
    api_contract_version: str
    get_runtime_status_handler: GetRuntimeStatusHandler | None
    update_runtime_mode_handler: UpdateRuntimeModeHandler | None


def get_runtime_route_dependencies(request: Request) -> RuntimeRouteDependencies:
    container = get_api_container(request)

    return RuntimeRouteDependencies(
        api_contract_version=container.api_contract_version,
        get_runtime_status_handler=container.get_runtime_status_handler,
        update_runtime_mode_handler=container.update_runtime_mode_handler,
    )


RuntimeRouteDependency = Annotated[
    RuntimeRouteDependencies,
    Depends(get_runtime_route_dependencies),
]
