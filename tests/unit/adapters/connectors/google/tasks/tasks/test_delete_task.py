from google_work_agent.adapters.connectors.google.tasks.tasks.delete_task import DeleteTaskOperation


def test_operation_binds_exact_tool_id() -> None:
    assert DeleteTaskOperation.tool_id == "tasks_delete_task"
