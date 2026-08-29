"""Canonical Google provider operation for tasks get task."""

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    credential_provider as workspace_support,
)


def _tasks_get_task(
    state: workspace_support.GoogleWorkspaceCredentialProvider, arguments: dict[str, object]
) -> dict[str, object]:
    task_list_id = workspace_support._text_argument(arguments, "task_list_id", maximum=2048)
    task_id = workspace_support._text_argument(arguments, "task_id", maximum=2048)
    task_list_path = workspace_support.quote(task_list_id, safe="")
    task_path = workspace_support.quote(task_id, safe="")
    payload = workspace_support._google_api(
        state, f"https://tasks.googleapis.com/tasks/v1/lists/{task_list_path}/tasks/{task_path}"
    )
    return {"item": workspace_support._task_snapshot(payload, task_list_id)}


class GetTaskOperation:
    tool_id = "tasks_get_task"

    def execute(
        self,
        state: workspace_support.GoogleWorkspaceCredentialProvider,
        arguments: dict[str, object],
    ) -> dict[str, object]:
        return _tasks_get_task(state, arguments)


__all__ = ["GetTaskOperation"]
