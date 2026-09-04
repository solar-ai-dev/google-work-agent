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
        {"format": "full"},
    )
    messages = workspace_support._object_list(payload.get("messages"))
    message_headers = [workspace_support._headers(message) for message in messages]
    headers = message_headers[0] if message_headers else {}
    message_ids = tuple(workspace_support._required_response_text(item, "id") for item in messages)
    participants = tuple(
        dict.fromkeys(
            value
            for item in message_headers
            for value in (item.get("from"), item.get("to"))
            if value
        )
    )
    latest = workspace_support._latest_gmail_message(messages) if messages else None
    return {
        "item": workspace_support._snapshot(
            "gmail_thread",
            thread_id,
            None,
            message_ids,
            payload.get("historyId"),
            {
                "subject": headers.get("subject", thread_id),
                "snippet": workspace_support._optional_text(
                    payload.get("snippet")
                    if payload.get("snippet") is not None
                    else None if latest is None else latest.get("snippet")
                ),
                "participants": list(participants),
                "message_ids": list(message_ids),
                "body": _thread_body(messages),
            },
        )
    }


def _thread_body(messages: list[dict[str, object]]) -> str | None:
    blocks: list[str] = []
    for message in messages:
        headers = workspace_support._headers(message)
        lines = [
            f"From: {headers['from']}" if headers.get("from") else None,
            f"To: {headers['to']}" if headers.get("to") else None,
            f"Date: {headers['date']}" if headers.get("date") else None,
            f"Subject: {headers['subject']}" if headers.get("subject") else None,
        ]
        body = workspace_support._gmail_message_body(message)
        if body is None:
            body = workspace_support._optional_text(message.get("snippet"))
        block = "\n".join([line for line in lines if line] + ([body] if body else []))
        if block:
            blocks.append(block)
    return workspace_support._optional_text("\n\n".join(blocks))


class GetThreadOperation:
    tool_id = "gmail_get_thread"

    def execute(
        self,
        state: workspace_support.GoogleWorkspaceCredentialProvider,
        arguments: dict[str, object],
    ) -> dict[str, object]:
        return _gmail_get_thread(state, arguments)


__all__ = ["GetThreadOperation"]
