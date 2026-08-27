from google_work_agent.adapters.connectors.google.gmail.attachments.get_attachment import (
    GetAttachmentOperation,
)


def test_operation_binds_exact_tool_id() -> None:
    assert GetAttachmentOperation.tool_id == "gmail_get_attachment"
