"""Canonical Google provider operation for tasks update task."""

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    credential_provider as workspace_support,
)


def _tasks_update_task(
    state: workspace_support.GoogleWorkspaceCredentialProvider, arguments: dict[str, object]
) -> dict[str, object]:
    task_list_id = workspace_support._text_argument(arguments, "task_list_id", maximum=2048)
    task_id = workspace_support._text_argument(arguments, "task_id", maximum=2048)
    payload = workspace_support._dict_argument(arguments, "payload")
    workspace_support._validate_claim_context(
        state,
        tool_name="tasks_update_task",
        claim_context=arguments.get("claim_context"),
        execution_arguments=workspace_support._execution_arguments(arguments),
    )
    body = workspace_support._task_write_body(payload, title_required=False)
    if not body:
        raise workspace_support._WorkspaceToolError("INVALID_ARGUMENT")
    task_list_path = workspace_support.quote(task_list_id, safe="")
    task_path = workspace_support.quote(task_id, safe="")
    response = workspace_support._google_api_call(
        state,
        "PATCH",
        f"https://tasks.googleapis.com/tasks/v1/lists/{task_list_path}/tasks/{task_path}",
        body=body,
    )
    return {"item": workspace_support._task_snapshot(response, task_list_id)}


class UpdateTaskOperation:
    tool_id = "tasks_update_task"

    def execute(
        self,
        state: workspace_support.GoogleWorkspaceCredentialProvider,
        arguments: dict[str, object],
    ) -> dict[str, object]:
        return _tasks_update_task(state, arguments)


__all__ = ["UpdateTaskOperation"]
