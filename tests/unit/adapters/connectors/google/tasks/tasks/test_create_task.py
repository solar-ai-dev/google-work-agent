from google_work_agent.adapters.connectors.google.tasks.tasks.create_task import CreateTaskOperation


def test_operation_binds_exact_tool_id() -> None:
    assert CreateTaskOperation.tool_id == "tasks_create_task"
