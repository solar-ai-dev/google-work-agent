from google_work_agent.adapters.connectors.google.tasks.tasklists.list_tasklists import (
    ListTasklistsOperation,
)


def test_operation_binds_exact_tool_id() -> None:
    assert ListTasklistsOperation.tool_id == "tasks_list_tasklists"
