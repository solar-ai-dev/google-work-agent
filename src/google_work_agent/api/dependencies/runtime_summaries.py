"""Runtime-summary route dependency contract and provider."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from google_work_agent.api.dependencies.request_context import get_api_container


@dataclass(frozen=True, slots=True)
class SafeModeRouteState:
    enabled: bool
    reason_codes: tuple[str, ...]
    allowed_operations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RuntimeRouteDependencies:
    api_contract_version: str
    get_runtime_status_handler: Callable[[], object | None]
    update_runtime_mode_handler: Callable[[], object | None]
    safe_mode_state: Callable[[], SafeModeRouteState | None]


def get_runtime_route_dependencies(request: Request) -> RuntimeRouteDependencies:
    container = get_api_container(request)

    def safe_mode_state() -> SafeModeRouteState | None:
        controller = container.safe_mode_controller
        if controller is None:
            return None
        state = controller.snapshot()
        return SafeModeRouteState(
            enabled=state.enabled,
            reason_codes=tuple(state.reason_codes),
            allowed_operations=tuple(item.value for item in state.allowed_operations),
        )

    return RuntimeRouteDependencies(
        api_contract_version=container.api_contract_version,
        get_runtime_status_handler=lambda: container.get_runtime_status_handler,
        update_runtime_mode_handler=lambda: container.update_runtime_mode_handler,
        safe_mode_state=safe_mode_state,
    )


RuntimeRouteDependency = Annotated[
    RuntimeRouteDependencies,
    Depends(get_runtime_route_dependencies),
]
