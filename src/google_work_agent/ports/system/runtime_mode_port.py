"""Process-local requested LLM runtime-mode boundary."""

from __future__ import annotations

from typing import Literal, Protocol

from google_work_agent.ports.system.contracts.operational_command_replay import (
    OperationalReconcileResultV1,
)

type RequestedRuntimeModeV1 = Literal["AUTO", "LOCAL_GPU", "API_LLM"]


class RuntimeModePort(Protocol):
    def get_requested_mode(self) -> RequestedRuntimeModeV1: ...

    def set_requested_mode(
        self, requested_mode: RequestedRuntimeModeV1, operation_ref: str
    ) -> RequestedRuntimeModeV1: ...

    def reconcile_update(
        self, operation_ref: str, requested_mode: RequestedRuntimeModeV1
    ) -> OperationalReconcileResultV1: ...


__all__ = ["RequestedRuntimeModeV1", "RuntimeModePort"]
