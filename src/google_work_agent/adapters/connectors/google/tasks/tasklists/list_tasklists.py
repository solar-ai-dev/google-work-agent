"""Canonical Google provider operation for tasks list tasklists."""

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    credential_provider as workspace_support,
)


def _tasks_list_tasklists(
    state: workspace_support.GoogleWorkspaceCredentialProvider, arguments: dict[str, object]
) -> dict[str, object]:
    payload = workspace_support._google_api(
        state,
        "https://tasks.googleapis.com/tasks/v1/users/@me/lists",
        workspace_support._page_params(arguments),
    )
    items = [
        workspace_support._snapshot(
            "task_list",
            workspace_support._required_response_text(item, "id"),
            None,
            (),
            item.get("updated"),
            {
                "title": workspace_support._optional_text(item.get("title"))
                or workspace_support._required_response_text(item, "id"),
                "kind": workspace_support._optional_text(item.get("kind")),
            },
        )
        for item in workspace_support._object_list(payload.get("items"))
    ]
    return {
        "items": items,
        "next_page_token": workspace_support._optional_text(payload.get("nextPageToken")),
    }


class ListTasklistsOperation:
    tool_id = "tasks_list_tasklists"

    def execute(
        self,
        state: workspace_support.GoogleWorkspaceCredentialProvider,
        arguments: dict[str, object],
    ) -> dict[str, object]:
        return _tasks_list_tasklists(state, arguments)


__all__ = ["ListTasklistsOperation"]
