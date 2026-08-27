from google_work_agent.adapters.connectors.google.calendar.events.update_event import (
    UpdateEventOperation,
)


def test_operation_binds_exact_tool_id() -> None:
    assert UpdateEventOperation.tool_id == "calendar_update_event"
