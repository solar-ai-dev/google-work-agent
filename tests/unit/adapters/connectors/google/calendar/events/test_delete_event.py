from google_work_agent.adapters.connectors.google.calendar.events.delete_event import (
    DeleteEventOperation,
)


def test_operation_binds_exact_tool_id() -> None:
    assert DeleteEventOperation.tool_id == "calendar_delete_event"
