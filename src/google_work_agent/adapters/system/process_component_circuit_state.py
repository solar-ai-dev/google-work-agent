"""Thread-safe process-local component circuit state."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock

from google_work_agent.ports.system.component_circuit_state_port import (
    ComponentCircuitKeyV1,
    ComponentCircuitStatePort,
    ComponentCircuitStateV1,
)


@dataclass(slots=True)
class ProcessComponentCircuitStateAdapter(ComponentCircuitStatePort):
    failure_threshold: int = 3
    open_duration_ms: int = 30_000
    _states: dict[ComponentCircuitKeyV1, ComponentCircuitStateV1] = field(
        default_factory=dict, init=False
    )
    _lock: RLock = field(default_factory=RLock, init=False)

    def __post_init__(self) -> None:
        if self.failure_threshold <= 0 or self.open_duration_ms <= 0:
            raise ValueError("circuit threshold and open duration must be positive")

    def get_state(self, key: ComponentCircuitKeyV1) -> ComponentCircuitStateV1:
        with self._lock:
            return self._states.get(key, _closed(key))

    def record_technical_failure(
        self, key: ComponentCircuitKeyV1, failure_code: str, now_ms: int
    ) -> ComponentCircuitStateV1:
        if not failure_code.strip():
            raise ValueError("failure_code is required")
        with self._lock:
            current = self._states.get(key, _closed(key))
            failures = current.consecutive_technical_failures + 1
            is_open = failures >= self.failure_threshold
            state = ComponentCircuitStateV1(
                schema_version=1,
                key=key,
                state="OPEN" if is_open else "CLOSED",
                consecutive_technical_failures=failures,
                retry_at_ms=now_ms + self.open_duration_ms if is_open else None,
                last_failure_code=failure_code,
            )
            self._states[key] = state
            return state

    def record_success(self, key: ComponentCircuitKeyV1, now_ms: int) -> ComponentCircuitStateV1:
        del now_ms
        with self._lock:
            state = _closed(key)
            self._states[key] = state
            return state


def _closed(key: ComponentCircuitKeyV1) -> ComponentCircuitStateV1:
    return ComponentCircuitStateV1(
        schema_version=1,
        key=key,
        state="CLOSED",
        consecutive_technical_failures=0,
        retry_at_ms=None,
        last_failure_code=None,
    )
