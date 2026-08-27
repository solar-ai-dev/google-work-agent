from google_work_agent.adapters.connectors.google.gmail.messages.send_message import (
    SendMessageOperation,
)


def test_operation_binds_exact_tool_id() -> None:
    assert SendMessageOperation.tool_id == "gmail_send"
