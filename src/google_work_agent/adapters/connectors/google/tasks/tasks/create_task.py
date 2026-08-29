"""Canonical Google provider operation for tasks create task."""

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    credential_provider as workspace_support,
)


def _tasks_create_task(
    state: workspace_support.GoogleWorkspaceCredentialProvider, arguments: dict[str, object]
) -> dict[str, object]:
    task_list_id = workspace_support._text_argument(arguments, "task_list_id", maximum=2048)
    payload = workspace_support._dict_argument(arguments, "payload")
    workspace_support._validate_claim_context(
        state,
        tool_name="tasks_create_task",
        claim_context=arguments.get("claim_context"),
        execution_arguments=workspace_support._execution_arguments(arguments),
    )
    body = workspace_support._task_write_body(payload, title_required=True)
    task_list_path = workspace_support.quote(task_list_id, safe="")
    response = workspace_support._google_api_post(
        state,
        f"https://tasks.googleapis.com/tasks/v1/lists/{task_list_path}/tasks",
        body,
    )
    return {"item": workspace_support._task_snapshot(response, task_list_id)}


class CreateTaskOperation:
    tool_id = "tasks_create_task"

    def execute(
        self,
        state: workspace_support.GoogleWorkspaceCredentialProvider,
        arguments: dict[str, object],
    ) -> dict[str, object]:
        return _tasks_create_task(state, arguments)


__all__ = ["CreateTaskOperation"]
