from google_work_agent.adapters.connectors.google.tasks.tasks.update_task import UpdateTaskOperation


def test_operation_binds_exact_tool_id() -> None:
    assert UpdateTaskOperation.tool_id == "tasks_update_task"
