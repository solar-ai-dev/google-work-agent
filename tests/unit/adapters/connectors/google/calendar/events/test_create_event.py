from google_work_agent.adapters.connectors.google.calendar.events.create_event import (
    CreateEventOperation,
)


def test_operation_binds_exact_tool_id() -> None:
    assert CreateEventOperation.tool_id == "calendar_create_event"
