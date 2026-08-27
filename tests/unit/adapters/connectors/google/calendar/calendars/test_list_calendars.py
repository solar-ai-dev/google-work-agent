from google_work_agent.adapters.connectors.google.calendar.calendars.list_calendars import (
    ListCalendarsOperation,
)


def test_operation_binds_exact_tool_id() -> None:
    assert ListCalendarsOperation.tool_id == "calendar_list_calendars"
