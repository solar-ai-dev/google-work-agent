"""Canonical Google provider operation for tasks list tasks."""

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    credential_provider as workspace_support,
)


def _tasks_list_tasks(
    state: workspace_support.GoogleWorkspaceCredentialProvider, arguments: dict[str, object]
) -> dict[str, object]:
    task_list_id = workspace_support._text_argument(arguments, "task_list_id", maximum=2048)
    show_completed = arguments.get("show_completed", False)
    show_hidden = arguments.get("show_hidden", False)
    show_deleted = arguments.get("show_deleted", False)
    if not all(isinstance(value, bool) for value in (show_completed, show_hidden, show_deleted)):
        raise workspace_support._WorkspaceToolError("INVALID_ARGUMENT")
    params = workspace_support._page_params(arguments)
    params["showCompleted"] = "true" if show_completed else "false"
    params["showHidden"] = "true" if show_hidden else "false"
    params["showDeleted"] = "true" if show_deleted else "false"
    task_list_path = workspace_support.quote(task_list_id, safe="")
    payload = workspace_support._google_api(
        state,
        f"https://tasks.googleapis.com/tasks/v1/lists/{task_list_path}/tasks",
        params,
    )
    items = [
        workspace_support._task_snapshot(item, task_list_id)
        for item in workspace_support._object_list(payload.get("items"))
    ]
    return {
        "items": items,
        "next_page_token": workspace_support._optional_text(payload.get("nextPageToken")),
    }


class ListTasksOperation:
    tool_id = "tasks_list_tasks"

    def execute(
        self,
        state: workspace_support.GoogleWorkspaceCredentialProvider,
        arguments: dict[str, object],
    ) -> dict[str, object]:
        return _tasks_list_tasks(state, arguments)


__all__ = ["ListTasksOperation"]
