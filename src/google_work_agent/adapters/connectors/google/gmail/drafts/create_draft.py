"""Canonical Google provider operation for gmail create draft."""

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    credential_provider as workspace_support,
)


def _gmail_create_draft(
    state: workspace_support.GoogleWorkspaceCredentialProvider, arguments: dict[str, object]
) -> dict[str, object]:
    payload = workspace_support._dict_argument(arguments, "payload")
    workspace_support._validate_claim_context(
        state,
        tool_name="gmail_create_draft",
        claim_context=arguments.get("claim_context"),
        execution_arguments=workspace_support._execution_arguments(arguments),
    )
    mime_bytes = workspace_support._build_gmail_mime(payload)
    body: dict[str, object] = {"message": {"raw": workspace_support._b64url_encode(mime_bytes)}}
    thread_id = workspace_support._optional_text(payload.get("thread_id"))
    if thread_id:
        workspace_support.cast(dict[str, object], body["message"])["threadId"] = thread_id
    response = workspace_support._google_api_post(
        state, "https://gmail.googleapis.com/gmail/v1/users/me/drafts", body
    )
    return {"item": workspace_support._gmail_draft_snapshot(response)}


class CreateDraftOperation:
    tool_id = "gmail_create_draft"

    def execute(
        self,
        state: workspace_support.GoogleWorkspaceCredentialProvider,
        arguments: dict[str, object],
    ) -> dict[str, object]:
        return _gmail_create_draft(state, arguments)


__all__ = ["CreateDraftOperation"]
