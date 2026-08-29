"""Canonical Google provider operation for gmail get draft."""

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    credential_provider as workspace_support,
)


def _gmail_get_draft(
    state: workspace_support.GoogleWorkspaceCredentialProvider, arguments: dict[str, object]
) -> dict[str, object]:
    draft_id = workspace_support._text_argument(arguments, "draft_id", maximum=2048)
    draft_path = workspace_support.quote(draft_id, safe="")
    payload = workspace_support._google_api(
        state,
        f"https://gmail.googleapis.com/gmail/v1/users/me/drafts/{draft_path}",
        {"format": "metadata"},
    )
    return {"item": workspace_support._gmail_draft_snapshot(payload)}


class GetDraftOperation:
    tool_id = "gmail_get_draft"

    def execute(
        self,
        state: workspace_support.GoogleWorkspaceCredentialProvider,
        arguments: dict[str, object],
    ) -> dict[str, object]:
        return _gmail_get_draft(state, arguments)


__all__ = ["GetDraftOperation"]
