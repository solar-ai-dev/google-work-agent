from google_work_agent.adapters.connectors.google.calendar.freebusy.query_freebusy import (
    QueryFreebusyOperation,
)


def test_operation_binds_exact_tool_id() -> None:
    assert QueryFreebusyOperation.tool_id == "calendar_query_freebusy"
