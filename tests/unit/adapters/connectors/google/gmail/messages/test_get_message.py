from google_work_agent.adapters.connectors.google.gmail.messages.get_message import (
    GetMessageOperation,
)


def test_operation_binds_exact_tool_id() -> None:
    assert GetMessageOperation.tool_id == "gmail_get_message"
