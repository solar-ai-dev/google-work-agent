"""Record only technical success/failure in the component circuit."""

from dataclasses import dataclass
from typing import Literal

from google_work_agent.ports.system.component_circuit_state_port import (
    ComponentCircuitKey,
    ComponentCircuitStatePort,
    ComponentCircuitStateV1,
)


@dataclass(frozen=True, slots=True)
class RecordComponentCallResultCommandV1:
    schema_version: Literal[1]
    key: ComponentCircuitKey
    outcome: Literal["SUCCESS", "TECHNICAL_FAILURE"]
    failure_code: str | None = None
    now_ms: int = 0


@dataclass(frozen=True, slots=True)
class RecordComponentCallResultResultV1:
    schema_version: Literal[1]
    key: ComponentCircuitKey
    state: ComponentCircuitStateV1
    transition: Literal["UNCHANGED", "OPENED", "CLOSED", "REOPENED"]


class RecordComponentCallResultHandler:
    def __init__(self, port: ComponentCircuitStatePort) -> None:
        self._port = port

    def __call__(
        self, command: RecordComponentCallResultCommandV1
    ) -> RecordComponentCallResultResultV1:
        if command.schema_version != 1 or command.now_ms < 0:
            raise ValueError("invalid component-circuit result command")
        before = self._port.get_state(command.key)
        if command.outcome == "SUCCESS":
            if command.failure_code is not None:
                raise ValueError("SUCCESS must not include failure_code")
            state = self._port.record_success(command.key, command.now_ms)
        elif command.outcome == "TECHNICAL_FAILURE" and command.failure_code:
            state = self._port.record_technical_failure(
                command.key, command.failure_code, command.now_ms
            )
        else:
            raise ValueError("only SUCCESS or a coded TECHNICAL_FAILURE may update the circuit")
        transition: Literal["UNCHANGED", "OPENED", "CLOSED", "REOPENED"]
        if before.state == "CLOSED" and state.state == "OPEN":
            transition = "OPENED"
        elif before.state == "OPEN" and state.state == "CLOSED":
            transition = "CLOSED"
        elif before.state == "OPEN" and state.state == "OPEN":
            transition = "REOPENED"
        else:
            transition = "UNCHANGED"
        return RecordComponentCallResultResultV1(1, command.key, state, transition)


__all__ = [
    "RecordComponentCallResultCommandV1",
    "RecordComponentCallResultHandler",
    "RecordComponentCallResultResultV1",
]
