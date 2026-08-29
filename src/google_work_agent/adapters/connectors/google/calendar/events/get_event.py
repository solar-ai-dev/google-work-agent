"""Canonical Google provider operation for calendar get event."""

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    credential_provider as workspace_support,
)


def _calendar_get_event(
    state: workspace_support.GoogleWorkspaceCredentialProvider, arguments: dict[str, object]
) -> dict[str, object]:
    calendar_id = workspace_support._text_argument(arguments, "calendar_id", maximum=2048)
    event_id = workspace_support._text_argument(arguments, "event_id", maximum=2048)
    calendar_path = workspace_support.quote(calendar_id, safe="")
    event_path = workspace_support.quote(event_id, safe="")
    payload = workspace_support._google_api(
        state,
        f"https://www.googleapis.com/calendar/v3/calendars/{calendar_path}/events/{event_path}",
    )
    return {"item": workspace_support._event_snapshot(payload, calendar_id)}


class GetEventOperation:
    tool_id = "calendar_get_event"

    def execute(
        self,
        state: workspace_support.GoogleWorkspaceCredentialProvider,
        arguments: dict[str, object],
    ) -> dict[str, object]:
        return _calendar_get_event(state, arguments)


__all__ = ["GetEventOperation"]
