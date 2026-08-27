from google_work_agent.adapters.connectors.google.calendar.events.list_events import (
    ListEventsOperation,
)


def test_operation_binds_exact_tool_id() -> None:
    assert ListEventsOperation.tool_id == "calendar_list_events"
