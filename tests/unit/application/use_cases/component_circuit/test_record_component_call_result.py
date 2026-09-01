import pytest

from google_work_agent.adapters.system.process_component_circuit_state import (
    ProcessComponentCircuitStateAdapter,
)
from google_work_agent.application.use_cases.component_circuit.record_component_call_result import (
    RecordComponentCallResultCommandV1,
    RecordComponentCallResultHandler,
)
from google_work_agent.ports.system.component_circuit_state_port import ComponentCircuitKey

KEY = ComponentCircuitKey(1, "LLM_RUNTIME", None, "API_LLM")


def test_record_component_call_result_opens_and_success_resets_circuit() -> None:
    port = ProcessComponentCircuitStateAdapter(failure_threshold=2, open_duration_ms=50)
    handler = RecordComponentCallResultHandler(port)

    first = handler(RecordComponentCallResultCommandV1(1, KEY, "TECHNICAL_FAILURE", "TIMEOUT", 10))
    opened = handler(RecordComponentCallResultCommandV1(1, KEY, "TECHNICAL_FAILURE", "TIMEOUT", 11))
    closed = handler(RecordComponentCallResultCommandV1(1, KEY, "SUCCESS", None, 12))

    assert first.transition == "UNCHANGED"
    assert opened.transition == "OPENED"
    assert opened.state.retry_at_ms == 61
    assert closed.transition == "CLOSED"
    assert closed.state.consecutive_technical_failures == 0


@pytest.mark.parametrize(
    "command",
    [
        RecordComponentCallResultCommandV1(1, KEY, "SUCCESS", "SHOULD_BE_EMPTY", 1),
        RecordComponentCallResultCommandV1(1, KEY, "TECHNICAL_FAILURE", None, 1),
    ],
)
def test_record_component_call_result_rejects_invalid_outcome_shape(
    command: RecordComponentCallResultCommandV1,
) -> None:
    handler = RecordComponentCallResultHandler(ProcessComponentCircuitStateAdapter())
    with pytest.raises(ValueError):
        handler(command)
