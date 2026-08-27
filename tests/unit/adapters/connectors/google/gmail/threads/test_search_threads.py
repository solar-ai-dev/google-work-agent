from google_work_agent.adapters.connectors.google.gmail.threads.search_threads import (
    SearchThreadsOperation,
)


def test_operation_binds_exact_tool_id() -> None:
    assert SearchThreadsOperation.tool_id == "gmail_search_threads"
