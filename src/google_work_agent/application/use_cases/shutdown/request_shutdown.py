"""Request graceful shutdown through crash-safe operational replay."""

from dataclasses import asdict, dataclass
from typing import Any, cast

from google_work_agent.application.use_cases.operational_replay import execute_operational_command
from google_work_agent.ports.system.operational_command_replay_port import (
    OperationalCommandReplayPort,
)
from google_work_agent.ports.system.shutdown_port import ShutdownAcceptedV1, ShutdownPort


@dataclass(frozen=True, slots=True)
class RequestShutdownCommand:
    command_id: str


@dataclass(frozen=True, slots=True)
class RequestShutdownResult:
    shutdown: ShutdownAcceptedV1
    operation_ref: str
    replayed: bool


class RequestShutdownHandler:
    def __init__(self, *, shutdown: ShutdownPort, replay: OperationalCommandReplayPort) -> None:
        self._shutdown = shutdown
        self._replay = replay

    def __call__(self, command: RequestShutdownCommand) -> RequestShutdownResult:
        def execute(ref: str) -> tuple[str, dict[str, object]]:
            value = self._shutdown.request_shutdown(ref)
            return ref, asdict(value)

        outcome = execute_operational_command(
            replay_port=self._replay,
            command_id=command.command_id,
            operation_kind="REQUEST_SHUTDOWN",
            request_payload={},
            reconcile=self._shutdown.reconcile_shutdown,
            execute=execute,
        )
        return RequestShutdownResult(
            shutdown=ShutdownAcceptedV1(**cast(Any, outcome.bounded_result)),
            operation_ref=outcome.operation_ref,
            replayed=outcome.replayed,
        )


__all__ = ["RequestShutdownCommand", "RequestShutdownHandler", "RequestShutdownResult"]
