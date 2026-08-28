"""Update the process-local requested runtime mode with crash-safe replay."""

from dataclasses import dataclass
from typing import cast

from google_work_agent.application.use_cases.operational_replay import execute_operational_command
from google_work_agent.ports.system.operational_command_replay_port import (
    OperationalCommandReplayPort,
)
from google_work_agent.ports.system.runtime_mode_port import RequestedRuntimeModeV1, RuntimeModePort


@dataclass(frozen=True, slots=True)
class UpdateRuntimeModeCommand:
    command_id: str
    requested_mode: RequestedRuntimeModeV1


@dataclass(frozen=True, slots=True)
class UpdateRuntimeModeResult:
    requested_mode: RequestedRuntimeModeV1
    operation_ref: str
    replayed: bool


class UpdateRuntimeModeHandler:
    def __init__(
        self, *, runtime_mode: RuntimeModePort, replay: OperationalCommandReplayPort
    ) -> None:
        self._runtime_mode = runtime_mode
        self._replay = replay

    def __call__(self, command: UpdateRuntimeModeCommand) -> UpdateRuntimeModeResult:
        outcome = execute_operational_command(
            replay_port=self._replay,
            command_id=command.command_id,
            operation_kind="UPDATE_RUNTIME_MODE",
            request_payload={"requested_mode": command.requested_mode},
            reconcile=lambda ref: self._runtime_mode.reconcile_update(ref, command.requested_mode),
            execute=lambda ref: (
                ref,
                {
                    "requested_mode": self._runtime_mode.set_requested_mode(
                        command.requested_mode, ref
                    )
                },
            ),
        )
        payload = cast(dict[str, object], outcome.bounded_result)
        return UpdateRuntimeModeResult(
            requested_mode=cast(RequestedRuntimeModeV1, payload["requested_mode"]),
            operation_ref=outcome.operation_ref,
            replayed=outcome.replayed,
        )


__all__ = ["UpdateRuntimeModeCommand", "UpdateRuntimeModeHandler", "UpdateRuntimeModeResult"]
