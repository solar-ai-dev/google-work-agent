"""Safe-mode state and operation gating."""

from __future__ import annotations

from dataclasses import dataclass

from google_work_agent.ports import ReadinessCheckResult, ReadinessState, RuntimeOperation


@dataclass(frozen=True, slots=True)
class SafeModeState:
    enabled: bool
    reason_codes: tuple[str, ...] = ()
    allowed_operations: tuple[RuntimeOperation, ...] = (
        RuntimeOperation.SETTINGS,
        RuntimeOperation.BACKUP,
        RuntimeOperation.RESTORE,
        RuntimeOperation.SHUTDOWN,
        RuntimeOperation.DIAGNOSTICS,
    )


class SafeModeController:
    """In-memory safe-mode state."""

    def __init__(self, state: SafeModeState | None = None) -> None:
        self._state = state or SafeModeState(enabled=False, reason_codes=(), allowed_operations=())

    def snapshot(self) -> SafeModeState:
        return self._state

    def enable(self, *reason_codes: str) -> None:
        self._state = SafeModeState(enabled=True, reason_codes=tuple(reason_codes))

    def disable(self) -> None:
        self._state = SafeModeState(enabled=False, reason_codes=(), allowed_operations=())

    def readiness_check(self) -> ReadinessCheckResult:
        state = self.snapshot()
        if not state.enabled:
            return ReadinessCheckResult(name="safe_mode", state=ReadinessState.READY)
        return ReadinessCheckResult(
            name="safe_mode",
            state=ReadinessState.SAFE_MODE,
            detail=",".join(state.reason_codes) if state.reason_codes else "SAFE_MODE",
        )

    def allows(self, operation: RuntimeOperation) -> bool:
        state = self.snapshot()
        if not state.enabled:
            return True
        return operation in state.allowed_operations
