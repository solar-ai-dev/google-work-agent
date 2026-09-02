from google_work_agent.adapters.system.memory.sse_event_buffer import InMemorySseEventBuffer
from google_work_agent.ports.system.sse_event_buffer_port import RunSseEventV1


def _event(*, event_id: str, occurred_at_ms: int) -> RunSseEventV1:
    return RunSseEventV1(1, event_id, "run-1", None, occurred_at_ms, "RUN_UPDATED", {}, 1)


def test_in_memory_event__buffer_assigns_monotonic__ids_and_lists() -> None:
    buffer = InMemorySseEventBuffer(service_instance_id="svc-a", capacity_per_run=4)
    buffer.append(_event(event_id="", occurred_at_ms=1))
    buffer.append(_event(event_id="", occurred_at_ms=2))
    page = buffer.list_after("run-1", "svc-a:1", 4)
    assert [event.event_id for event in page.events] == ["svc-a:2"]
    assert page.cursor_status == "OK"


def test_in_memory_event__buffer_marks_evicted__or_invalid_cursor_expired() -> None:
    buffer = InMemorySseEventBuffer(service_instance_id="svc-a", capacity_per_run=2)
    for occurred_at_ms in range(1, 5):
        buffer.append(_event(event_id="", occurred_at_ms=occurred_at_ms))
    assert buffer.list_after("run-1", "svc-a:1", 2).cursor_status == "CURSOR_EXPIRED"
    assert buffer.list_after("run-1", "bad-cursor", 2).cursor_status == "CURSOR_EXPIRED"
