from google_work_agent.adapters.connectors.google.gmail.drafts.update_draft import (
    UpdateDraftOperation,
)


def test_operation_binds_exact_tool_id() -> None:
    assert UpdateDraftOperation.tool_id == "gmail_update_draft"
