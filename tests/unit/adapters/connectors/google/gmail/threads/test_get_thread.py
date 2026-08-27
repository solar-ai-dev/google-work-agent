from google_work_agent.adapters.connectors.google.gmail.threads.get_thread import GetThreadOperation


def test_operation_binds_exact_tool_id() -> None:
    assert GetThreadOperation.tool_id == "gmail_get_thread"
