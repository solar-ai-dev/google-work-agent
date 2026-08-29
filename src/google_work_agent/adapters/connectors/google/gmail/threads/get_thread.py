"""Canonical Google provider operation for gmail get thread."""

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    credential_provider as workspace_support,
)


def _gmail_get_thread(
    state: workspace_support.GoogleWorkspaceCredentialProvider, arguments: dict[str, object]
) -> dict[str, object]:
    thread_id = workspace_support._text_argument(arguments, "thread_id", maximum=2048)
    thread_path = workspace_support.quote(thread_id, safe="")
    payload = workspace_support._google_api(
        state,
        f"https://gmail.googleapis.com/gmail/v1/users/me/threads/{thread_path}",
        {"format": "metadata"},
    )
    messages = workspace_support._object_list(payload.get("messages"))
    headers = workspace_support._headers(messages[0]) if messages else {}
    message_ids = tuple(workspace_support._required_response_text(item, "id") for item in messages)
    participants = tuple(value for value in (headers.get("from"), headers.get("to")) if value)
    return {
        "item": workspace_support._snapshot(
            "gmail_thread",
            thread_id,
            None,
            message_ids,
            payload.get("historyId"),
            {
                "subject": headers.get("subject", thread_id),
                "snippet": workspace_support._optional_text(payload.get("snippet")),
                "participants": list(participants),
                "message_ids": list(message_ids),
            },
        )
    }


class GetThreadOperation:
    tool_id = "gmail_get_thread"

    def execute(
        self,
        state: workspace_support.GoogleWorkspaceCredentialProvider,
        arguments: dict[str, object],
    ) -> dict[str, object]:
        return _gmail_get_thread(state, arguments)


__all__ = ["GetThreadOperation"]
