"""Canonical Google provider operation for calendar delete event."""

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    credential_provider as workspace_support,
)


def _calendar_delete_event(
    state: workspace_support.GoogleWorkspaceCredentialProvider, arguments: dict[str, object]
) -> dict[str, object]:
    calendar_id = workspace_support._text_argument(arguments, "calendar_id", maximum=2048)
    event_id = workspace_support._text_argument(arguments, "event_id", maximum=2048)
    workspace_support._validate_claim_context(
        state,
        tool_name="calendar_delete_event",
        claim_context=arguments.get("claim_context"),
        execution_arguments=workspace_support._execution_arguments(arguments),
    )
    calendar_path = workspace_support.quote(calendar_id, safe="")
    event_path = workspace_support.quote(event_id, safe="")
    workspace_support._google_api_call(
        state,
        "DELETE",
        f"https://www.googleapis.com/calendar/v3/calendars/{calendar_path}/events/{event_path}",
    )
    return {
        "item": workspace_support._snapshot(
            "calendar_event",
            event_id,
            calendar_id,
            (calendar_id,),
            "deleted",
            {"status": "cancelled"},
        )
    }


class DeleteEventOperation:
    tool_id = "calendar_delete_event"

    def execute(
        self,
        state: workspace_support.GoogleWorkspaceCredentialProvider,
        arguments: dict[str, object],
    ) -> dict[str, object]:
        return _calendar_delete_event(state, arguments)


__all__ = ["DeleteEventOperation"]
