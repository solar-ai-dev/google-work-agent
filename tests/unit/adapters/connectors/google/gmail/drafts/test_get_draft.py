from google_work_agent.adapters.connectors.google.gmail.drafts.get_draft import GetDraftOperation


def test_operation_binds_exact_tool_id() -> None:
    assert GetDraftOperation.tool_id == "gmail_get_draft"
