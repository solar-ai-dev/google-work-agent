"""Single mutable process-local requested runtime mode."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock

from google_work_agent.ports.system.contracts.operational_command_replay import (
    OperationalReconcileResultV1,
)
from google_work_agent.ports.system.runtime_mode_port import RequestedRuntimeModeV1, RuntimeModePort


@dataclass(slots=True)
class ProcessRuntimeModeAdapter(RuntimeModePort):
    initial_mode: RequestedRuntimeModeV1
    _mode: RequestedRuntimeModeV1 = field(init=False)
    _applied: dict[str, RequestedRuntimeModeV1] = field(default_factory=dict, init=False)
    _lock: RLock = field(default_factory=RLock, init=False)

    def __post_init__(self) -> None:
        if self.initial_mode not in {"AUTO", "LOCAL_GPU", "API_LLM"}:
            raise ValueError("unsupported initial requested runtime mode")
        self._mode = self.initial_mode

    def get_requested_mode(self) -> RequestedRuntimeModeV1:
        with self._lock:
            return self._mode

    def set_requested_mode(
        self, requested_mode: RequestedRuntimeModeV1, operation_ref: str
    ) -> RequestedRuntimeModeV1:
        if requested_mode not in {"AUTO", "LOCAL_GPU", "API_LLM"}:
            raise ValueError("unsupported requested runtime mode")
        if not operation_ref.strip():
            raise ValueError("operation_ref is required")
        with self._lock:
            existing = self._applied.get(operation_ref)
            if existing is not None and existing != requested_mode:
                raise ValueError("operation_ref already applied to a different runtime mode")
            self._mode = requested_mode
            self._applied[operation_ref] = requested_mode
            return self._mode

    def reconcile_update(
        self, operation_ref: str, requested_mode: RequestedRuntimeModeV1
    ) -> OperationalReconcileResultV1:
        with self._lock:
            existing = self._applied.get(operation_ref)
            if existing == requested_mode:
                return OperationalReconcileResultV1(
                    status="COMPLETED",
                    result_ref=operation_ref,
                    bounded_result={"requested_mode": requested_mode},
                )
            if existing is None:
                return OperationalReconcileResultV1(
                    status="SAFE_TO_RETRY",
                    result_ref=None,
                    bounded_result=None,
                )
            return OperationalReconcileResultV1(
                status="UNCERTAIN",
                result_ref=None,
                bounded_result=None,
            )
