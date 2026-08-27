from google_work_agent.adapters.connectors.google.calendar.events.get_event import GetEventOperation


def test_operation_binds_exact_tool_id() -> None:
    assert GetEventOperation.tool_id == "calendar_get_event"
