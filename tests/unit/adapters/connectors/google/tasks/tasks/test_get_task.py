from google_work_agent.adapters.connectors.google.tasks.tasks.get_task import GetTaskOperation


def test_operation_binds_exact_tool_id() -> None:
    assert GetTaskOperation.tool_id == "tasks_get_task"
