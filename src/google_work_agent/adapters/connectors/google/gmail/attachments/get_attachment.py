"""Canonical Google provider operation for gmail get attachment."""

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    credential_provider as workspace_support,
)


def _gmail_get_attachment(
    state: workspace_support.GoogleWorkspaceCredentialProvider, arguments: dict[str, object]
) -> dict[str, object]:
    """Return one Gmail attachment's bytes for the FastAPI download route to stream.

    This tool never touches Agent state, SQLite, or trace/audit output --
    the caller (a Local API route) streams the returned bytes straight to
    the browser and discards them. Attachments that would not fit inside a
    single stdio message are rejected rather than silently truncated.
    """
    message_id = workspace_support._text_argument(arguments, "message_id", maximum=2048)
    attachment_id = workspace_support._text_argument(arguments, "attachment_id", maximum=2048)
    message_path = workspace_support.quote(message_id, safe="")
    attachment_path = workspace_support.quote(attachment_id, safe="")
    payload = workspace_support._google_api(
        state,
        "https://gmail.googleapis.com/gmail/v1/users/me/messages/"
        f"{message_path}/attachments/{attachment_path}",
    )
    raw_value = workspace_support._optional_text(payload.get("data"))
    if raw_value is None:
        raise workspace_support._WorkspaceToolError("INVALID_MCP_OUTPUT", dispatch_started=True)
    data = workspace_support._b64url_decode(raw_value)
    if len(data) > workspace_support.MAX_ATTACHMENT_READ_BYTES:
        raise workspace_support._WorkspaceToolError("ATTACHMENT_TOO_LARGE", dispatch_started=True)
    return {
        "message_id": message_id,
        "attachment_id": attachment_id,
        "size_bytes": len(data),
        "sha256": workspace_support.hashlib.sha256(data).hexdigest(),
        "data_base64url": workspace_support._b64url_encode(data),
    }


class GetAttachmentOperation:
    tool_id = "gmail_get_attachment"

    def execute(
        self,
        state: workspace_support.GoogleWorkspaceCredentialProvider,
        arguments: dict[str, object],
    ) -> dict[str, object]:
        return _gmail_get_attachment(state, arguments)


__all__ = ["GetAttachmentOperation"]
