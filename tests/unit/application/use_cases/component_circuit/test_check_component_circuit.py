from dataclasses import dataclass

import pytest

from google_work_agent.application.use_cases.component_circuit.check_component_circuit import (
    CheckComponentCircuitHandler,
    CheckComponentCircuitQueryV1,
)
from google_work_agent.ports.system.component_circuit_state_port import (
    ComponentCircuitKey,
    ComponentCircuitStateV1,
)

KEY = ComponentCircuitKey(1, "CONNECTOR", "google-workspace", None)


@dataclass
class _StatePort:
    state: ComponentCircuitStateV1

    def get_state(self, key: ComponentCircuitKey) -> ComponentCircuitStateV1:
        assert key == KEY
        return self.state

    def record_technical_failure(self, *args: object) -> ComponentCircuitStateV1:
        raise AssertionError("query must not mutate circuit state")

    def record_success(self, *args: object) -> ComponentCircuitStateV1:
        raise AssertionError("query must not mutate circuit state")


@pytest.mark.parametrize(
    ("state", "now_ms", "allowed", "reason"),
    [
        ("CLOSED", 5, True, "OK"),
        ("OPEN", 9, False, "CIRCUIT_OPEN"),
        ("OPEN", 10, True, "OK"),
    ],
)
def test_check_component_circuit_obeys_retry_boundary(
    state: str, now_ms: int, allowed: bool, reason: str
) -> None:
    port = _StatePort(
        ComponentCircuitStateV1(
            1,
            KEY,
            state,  # type: ignore[arg-type]
            2 if state == "OPEN" else 0,
            10 if state == "OPEN" else None,
            "TIMEOUT" if state == "OPEN" else None,
        )
    )

    result = CheckComponentCircuitHandler(port)(CheckComponentCircuitQueryV1(1, KEY, now_ms))

    assert result.allowed is allowed
    assert result.reason_code == reason
    assert result.key == KEY
    assert result.state == state


def test_check_component_circuit_rejects_negative_time() -> None:
    port = _StatePort(ComponentCircuitStateV1(1, KEY, "CLOSED", 0, None, None))
    with pytest.raises(ValueError, match="invalid component-circuit query"):
        CheckComponentCircuitHandler(port)(CheckComponentCircuitQueryV1(1, KEY, -1))
