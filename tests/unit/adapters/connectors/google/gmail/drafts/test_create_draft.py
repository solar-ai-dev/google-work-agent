from google_work_agent.adapters.connectors.google.gmail.drafts.create_draft import (
    CreateDraftOperation,
)


def test_operation_binds_exact_tool_id() -> None:
    assert CreateDraftOperation.tool_id == "gmail_create_draft"
