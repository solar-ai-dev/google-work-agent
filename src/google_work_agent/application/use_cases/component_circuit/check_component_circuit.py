"""Read the canonical process-local component circuit state."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from google_work_agent.application.use_cases.component_circuit.record_component_call_result import (
    RecordComponentCallResultCommandV1,
    RecordComponentCallResultHandler,
)
from google_work_agent.ports.connector.connector_failure import (
    ConnectorFailureCode,
    ConnectorOperationFailure,
)
from google_work_agent.ports.connector.connector_read_port import (
    ConnectorReadPort,
    ConnectorReadResultV1,
    JsonValue,
)
from google_work_agent.ports.connector.connector_write_port import (
    ConnectorWritePort,
    ConnectorWriteResultV1,
)
from google_work_agent.ports.connector.contracts.validated_connector_tool_binding import (
    ValidatedConnectorToolBindingV1,
)
from google_work_agent.ports.system.component_circuit_state_port import (
    ComponentCircuitKey,
    ComponentCircuitStatePort,
)


@dataclass(frozen=True, slots=True)
class CheckComponentCircuitQueryV1:
    schema_version: Literal[1]
    key: ComponentCircuitKey
    now_ms: int


@dataclass(frozen=True, slots=True)
class CheckComponentCircuitResultV1:
    schema_version: Literal[1]
    key: ComponentCircuitKey
    allowed: bool
    state: Literal["CLOSED", "OPEN"]
    retry_at_ms: int | None
    reason_code: Literal["OK", "CIRCUIT_OPEN"]


class CheckComponentCircuitHandler:
    def __init__(self, port: ComponentCircuitStatePort) -> None:
        self._port = port

    def __call__(self, query: CheckComponentCircuitQueryV1) -> CheckComponentCircuitResultV1:
        if query.schema_version != 1 or query.now_ms < 0:
            raise ValueError("invalid component-circuit query")
        state = self._port.get_state(query.key)
        allowed = state.state == "CLOSED" or (
            state.retry_at_ms is not None and query.now_ms >= state.retry_at_ms
        )
        return CheckComponentCircuitResultV1(
            schema_version=1,
            key=query.key,
            allowed=allowed,
            state=state.state,
            retry_at_ms=state.retry_at_ms,
            reason_code="OK" if allowed else "CIRCUIT_OPEN",
        )


class CircuitProtectedConnectorReadPort(ConnectorReadPort):
    """Apply the canonical circuit gate to every Connector READ."""

    def __init__(
        self,
        *,
        delegate: ConnectorReadPort,
        connector_id: str,
        check: CheckComponentCircuitHandler,
        record: RecordComponentCallResultHandler,
        now_ms: Callable[[], int],
    ) -> None:
        self._delegate = delegate
        self._key = ComponentCircuitKey(1, "CONNECTOR", connector_id, None)
        self._check = check
        self._record = record
        self._now_ms = now_ms

    def execute_read(
        self,
        binding: ValidatedConnectorToolBindingV1,
        tool_arguments: dict[str, JsonValue],
    ) -> ConnectorReadResultV1:
        now_ms = self._now_ms()
        if not self._check(CheckComponentCircuitQueryV1(1, self._key, now_ms)).allowed:
            raise ConnectorOperationFailure(
                code=ConnectorFailureCode.CONNECTION_UNAVAILABLE,
                detail_code="COMPONENT_CIRCUIT_OPEN",
            )
        try:
            result = self._delegate.execute_read(binding, tool_arguments)
        except ConnectorOperationFailure as error:
            if error.code in _TECHNICAL_CONNECTOR_FAILURES:
                self._record(
                    RecordComponentCallResultCommandV1(
                        1, self._key, "TECHNICAL_FAILURE", error.code.value, now_ms
                    )
                )
            raise
        self._record(RecordComponentCallResultCommandV1(1, self._key, "SUCCESS", None, now_ms))
        return result


class CircuitProtectedConnectorWritePort(ConnectorWritePort):
    """Apply the canonical circuit gate to every Connector WRITE."""

    def __init__(
        self,
        *,
        delegate: ConnectorWritePort,
        connector_id: str,
        check: CheckComponentCircuitHandler,
        record: RecordComponentCallResultHandler,
        now_ms: Callable[[], int],
    ) -> None:
        self._delegate = delegate
        self._key = ComponentCircuitKey(1, "CONNECTOR", connector_id, None)
        self._check = check
        self._record = record
        self._now_ms = now_ms

    def execute_write(
        self,
        binding: ValidatedConnectorToolBindingV1,
        tool_arguments: dict[str, JsonValue],
        claim_token: dict[str, JsonValue],
    ) -> ConnectorWriteResultV1:
        now_ms = self._now_ms()
        if not self._check(CheckComponentCircuitQueryV1(1, self._key, now_ms)).allowed:
            return ConnectorWriteResultV1(
                1, False, "NOT_SENT", None, None, "COMPONENT_CIRCUIT_OPEN"
            )
        result = self._delegate.execute_write(binding, tool_arguments, claim_token)
        if result.success:
            outcome = RecordComponentCallResultCommandV1(1, self._key, "SUCCESS", None, now_ms)
        else:
            outcome = RecordComponentCallResultCommandV1(
                1,
                self._key,
                "TECHNICAL_FAILURE",
                result.error_code or "CONNECTOR_WRITE_FAILED",
                now_ms,
            )
        self._record(outcome)
        return result


_TECHNICAL_CONNECTOR_FAILURES = {
    ConnectorFailureCode.RATE_LIMITED,
    ConnectorFailureCode.UPSTREAM_UNAVAILABLE,
    ConnectorFailureCode.TIMEOUT,
    ConnectorFailureCode.CONNECTION_UNAVAILABLE,
    ConnectorFailureCode.MALFORMED_RESPONSE,
}


__all__ = [
    "CheckComponentCircuitHandler",
    "CheckComponentCircuitQueryV1",
    "CheckComponentCircuitResultV1",
    "CircuitProtectedConnectorReadPort",
    "CircuitProtectedConnectorWritePort",
]
