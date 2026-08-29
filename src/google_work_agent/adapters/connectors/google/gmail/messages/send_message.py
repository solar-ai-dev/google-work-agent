"""Canonical Google provider operation for gmail send."""

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    credential_provider as workspace_support,
)


def _gmail_send(
    state: workspace_support.GoogleWorkspaceCredentialProvider, arguments: dict[str, object]
) -> dict[str, object]:
    draft_id = workspace_support._text_argument(arguments, "draft_id", maximum=2048)
    recovery_fingerprint = workspace_support._optional_text(arguments.get("recovery_fingerprint"))
    workspace_support._validate_claim_context(
        state,
        tool_name="gmail_send",
        claim_context=arguments.get("claim_context"),
        execution_arguments=workspace_support._execution_arguments(arguments),
    )
    if recovery_fingerprint:
        workspace_support._embed_send_recovery_marker(
            state, draft_id=draft_id, recovery_fingerprint=recovery_fingerprint
        )
    response = workspace_support._google_api_post(
        state, "https://gmail.googleapis.com/gmail/v1/users/me/drafts/send", {"id": draft_id}
    )
    headers = workspace_support._headers(response)
    message_id = workspace_support._required_response_text(response, "id")
    return {
        "item": workspace_support._snapshot(
            "gmail_message",
            message_id,
            workspace_support._optional_text(response.get("threadId")),
            (),
            response.get("historyId"),
            {"subject": headers.get("subject"), "sent": True, "draft_id": draft_id},
        )
    }


class SendMessageOperation:
    tool_id = "gmail_send"

    def execute(
        self,
        state: workspace_support.GoogleWorkspaceCredentialProvider,
        arguments: dict[str, object],
    ) -> dict[str, object]:
        return _gmail_send(state, arguments)


__all__ = ["SendMessageOperation"]
