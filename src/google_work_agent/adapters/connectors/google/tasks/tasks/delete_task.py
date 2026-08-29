"""Canonical Google provider operation for tasks delete task."""

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    credential_provider as workspace_support,
)


def _tasks_delete_task(
    state: workspace_support.GoogleWorkspaceCredentialProvider, arguments: dict[str, object]
) -> dict[str, object]:
    task_list_id = workspace_support._text_argument(arguments, "task_list_id", maximum=2048)
    task_id = workspace_support._text_argument(arguments, "task_id", maximum=2048)
    workspace_support._validate_claim_context(
        state,
        tool_name="tasks_delete_task",
        claim_context=arguments.get("claim_context"),
        execution_arguments=workspace_support._execution_arguments(arguments),
    )
    task_list_path = workspace_support.quote(task_list_id, safe="")
    task_path = workspace_support.quote(task_id, safe="")
    workspace_support._google_api_call(
        state,
        "DELETE",
        f"https://tasks.googleapis.com/tasks/v1/lists/{task_list_path}/tasks/{task_path}",
    )
    return {
        "item": workspace_support._snapshot(
            "task", task_id, task_list_id, (task_list_id,), "deleted", {"status": "deleted"}
        )
    }


class DeleteTaskOperation:
    tool_id = "tasks_delete_task"

    def execute(
        self,
        state: workspace_support.GoogleWorkspaceCredentialProvider,
        arguments: dict[str, object],
    ) -> dict[str, object]:
        return _tasks_delete_task(state, arguments)


__all__ = ["DeleteTaskOperation"]
