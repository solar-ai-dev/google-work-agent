from google_work_agent.adapters.connectors.google.tasks.tasks.list_tasks import ListTasksOperation


def test_operation_binds_exact_tool_id() -> None:
    assert ListTasksOperation.tool_id == "tasks_list_tasks"
