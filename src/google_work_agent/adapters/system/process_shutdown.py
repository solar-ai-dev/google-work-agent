"""Graceful shutdown coordination."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from google_work_agent.ports.system.clock_port import ClockPort
from google_work_agent.ports.system.contracts.operational_command_replay import (
    OperationalReconcileResultV1,
)
from google_work_agent.ports.system.shutdown_port import ShutdownAcceptedV1


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


class ProcessShutdownAdapter:
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
        clock: ClockPort,
        marker_path: Path,
        timeout_seconds: float = 30.0,
        request_process_exit: Callable[[], None] | None = None,
    ) -> None:
        self._command_gate = command_gate
        self._coordinator = coordinator
        self._workflow_runtime = workflow_runtime
        self._observability = observability
        self._persistence = persistence
        self._mcp_transport = mcp_transport
        self._sessions = sessions
        self._clock = clock
        self._marker_path = marker_path
        self._timeout_seconds = timeout_seconds
        self._request_process_exit = request_process_exit or (lambda: None)

    def request_shutdown(self, operation_ref: str) -> ShutdownAcceptedV1:
        if not operation_ref.strip():
            raise ValueError("operation_ref is required")
        self._marker_path.parent.mkdir(parents=True, exist_ok=True)
        if self._marker_path.is_file():
            existing = json.loads(self._marker_path.read_text(encoding="utf-8"))
            if existing.get("operation_ref") == operation_ref:
                return ShutdownAcceptedV1(schema_version=1, accepted=True)
            if existing.get("status") != "COMPLETED":
                raise ValueError("shutdown marker belongs to an unresolved operation_ref")
        _atomic_write(
            self._marker_path,
            json.dumps({"operation_ref": operation_ref, "status": "ACCEPTED"}).encode("utf-8"),
        )
        started = self._clock.now_ms()
        errors: list[str] = []
        phase = ShutdownPhase.STOP_ACCEPTING_COMMANDS.value
        try:
            self._command_gate.stop_accepting_commands()
            phase = ShutdownPhase.STOP_COORDINATOR.value
            self._coordinator.stop_accepting()
            self._coordinator.shutdown(self._timeout_seconds)
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
        _atomic_write(
            self._marker_path,
            json.dumps(
                {
                    "operation_ref": operation_ref,
                    "status": status,
                    "phase": phase,
                    "duration_ms": self._clock.now_ms() - started,
                    "safe_error_codes": errors,
                },
                sort_keys=True,
            ).encode("utf-8"),
        )
        if status == "COMPLETED":
            self._request_process_exit()
        return ShutdownAcceptedV1(schema_version=1, accepted=True)

    def reconcile_shutdown(self, operation_ref: str) -> OperationalReconcileResultV1:
        if not self._marker_path.is_file():
            return OperationalReconcileResultV1("SAFE_TO_RETRY", None, None)
        payload = json.loads(self._marker_path.read_text(encoding="utf-8"))
        if payload.get("operation_ref") != operation_ref:
            return OperationalReconcileResultV1("SAFE_TO_RETRY", None, None)
        status = str(payload.get("status"))
        return OperationalReconcileResultV1(
            "COMPLETED" if status in {"ACCEPTED", "COMPLETED"} else "UNCERTAIN",
            operation_ref,
            {"accepted": True, "status": status},
        )


def _atomic_write(path: Path, data: bytes) -> None:
    temp_path = path.with_name(f".{path.name}.tmp")
    with temp_path.open("wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp_path, path)
