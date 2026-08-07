"""Graceful shutdown coordination."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from google_work_agent.ports import Clock


class ShutdownPhase(StrEnum):
    STOP_ACCEPTING_COMMANDS = "STOP_ACCEPTING_COMMANDS"
    STOP_COORDINATOR = "STOP_COORDINATOR"
    FLUSH_RUNTIME = "FLUSH_RUNTIME"
    FLUSH_OBSERVABILITY = "FLUSH_OBSERVABILITY"
    CHECKPOINT_WAL = "CHECKPOINT_WAL"
    CLOSE_PERSISTENCE = "CLOSE_PERSISTENCE"
    CLOSE_MCP = "CLOSE_MCP"
    INVALIDATE_SESSIONS = "INVALIDATE_SESSIONS"


class ComponentShutdownPort(Protocol):
    def stop_accepting_commands(self) -> None: ...
    def stop_accepting(self) -> None: ...
    def shutdown(self, timeout_seconds: float) -> None: ...
    def flush_or_checkpoint(self) -> None: ...
    def flush(self) -> None: ...
    def checkpoint_wal(self) -> None: ...
    def close(self) -> None: ...
    def invalidate_all(self) -> None: ...


@dataclass(frozen=True, slots=True)
class ShutdownReport:
    phase: str
    status: str
    duration_ms: int
    safe_error_codes: tuple[str, ...]


class GracefulShutdownCoordinator:
    def __init__(
        self,
        *,
        command_gate: ComponentShutdownPort,
        coordinator: ComponentShutdownPort,
        workflow_runtime: ComponentShutdownPort,
        observability: ComponentShutdownPort,
        persistence: ComponentShutdownPort,
        mcp_transport: ComponentShutdownPort,
        sessions: ComponentShutdownPort,
        clock: Clock,
    ) -> None:
        self._command_gate = command_gate
        self._coordinator = coordinator
        self._workflow_runtime = workflow_runtime
        self._observability = observability
        self._persistence = persistence
        self._mcp_transport = mcp_transport
        self._sessions = sessions
        self._clock = clock

    def shutdown(self, *, timeout_seconds: float) -> ShutdownReport:
        started = self._clock.now_ms()
        errors: list[str] = []
        phase = ShutdownPhase.STOP_ACCEPTING_COMMANDS.value
        try:
            self._command_gate.stop_accepting_commands()
            phase = ShutdownPhase.STOP_COORDINATOR.value
            self._coordinator.stop_accepting()
            self._coordinator.shutdown(timeout_seconds)
            phase = ShutdownPhase.FLUSH_RUNTIME.value
            self._workflow_runtime.flush_or_checkpoint()
            phase = ShutdownPhase.FLUSH_OBSERVABILITY.value
            self._observability.flush()
            phase = ShutdownPhase.CHECKPOINT_WAL.value
            self._persistence.checkpoint_wal()
            phase = ShutdownPhase.CLOSE_PERSISTENCE.value
            self._persistence.close()
            phase = ShutdownPhase.CLOSE_MCP.value
            self._mcp_transport.close()
            phase = ShutdownPhase.INVALIDATE_SESSIONS.value
            self._sessions.invalidate_all()
            status = "COMPLETED"
        except Exception as error:  # pragma: no cover - exercised through tests with doubles
            errors.append(type(error).__name__)
            status = "FAILED"
        return ShutdownReport(
            phase=phase,
            status=status,
            duration_ms=self._clock.now_ms() - started,
            safe_error_codes=tuple(errors),
        )
