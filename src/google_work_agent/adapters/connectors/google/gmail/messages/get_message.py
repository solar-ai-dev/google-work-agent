"""Canonical Google provider operation for gmail get message."""

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    credential_provider as workspace_support,
)


def _gmail_get_message(
    state: workspace_support.GoogleWorkspaceCredentialProvider, arguments: dict[str, object]
) -> dict[str, object]:
    """Return one Gmail message snapshot including its actual body text.

    Agent Retrieval acquisition (unlike the Sidebar UI detail endpoint) reads
    this tool's payload directly into SourceSegment/Evidence text, so it must
    fetch ``format=full`` and extract the real body -- ``format=metadata``
    only returns headers and would leave Gmail evidence bodyless.
    """
    message_id = workspace_support._text_argument(arguments, "message_id", maximum=2048)
    message_path = workspace_support.quote(message_id, safe="")
    payload = workspace_support._google_api(
        state,
        f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_path}",
        {"format": "full"},
    )
    headers = workspace_support._headers(payload)
    return {
        "item": workspace_support._snapshot(
            "gmail_message",
            message_id,
            workspace_support._optional_text(payload.get("threadId")),
            (),
            payload.get("historyId"),
            {
                "subject": headers.get("subject", message_id),
                "snippet": workspace_support._optional_text(payload.get("snippet")),
                "from": headers.get("from"),
                "to": headers.get("to"),
                "received_at": headers.get("date"),
                "body": workspace_support._gmail_message_body(payload),
                "attachments": workspace_support._gmail_attachment_metadata(payload),
            },
        )
    }


class GetMessageOperation:
    tool_id = "gmail_get_message"

    def execute(
        self,
        state: workspace_support.GoogleWorkspaceCredentialProvider,
        arguments: dict[str, object],
    ) -> dict[str, object]:
        return _gmail_get_message(state, arguments)


__all__ = ["GetMessageOperation"]
