"""Canonical Google provider operation for calendar list calendars."""

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    credential_provider as workspace_support,
)


def _calendar_list_calendars(
    state: workspace_support.GoogleWorkspaceCredentialProvider, arguments: dict[str, object]
) -> dict[str, object]:
    payload = workspace_support._google_api(
        state,
        "https://www.googleapis.com/calendar/v3/users/me/calendarList",
        workspace_support._page_params(arguments),
    )
    items = [
        workspace_support._snapshot(
            "calendar",
            workspace_support._required_response_text(item, "id"),
            None,
            (),
            item.get("etag"),
            {
                "summary": workspace_support._optional_text(item.get("summary"))
                or workspace_support._required_response_text(item, "id"),
                "time_zone": workspace_support._optional_text(item.get("timeZone")),
                "primary": item.get("primary") is True,
            },
        )
        for item in workspace_support._object_list(payload.get("items"))
    ]
    return {
        "items": items,
        "next_page_token": workspace_support._optional_text(payload.get("nextPageToken")),
    }


class ListCalendarsOperation:
    tool_id = "calendar_list_calendars"

    def execute(
        self,
        state: workspace_support.GoogleWorkspaceCredentialProvider,
        arguments: dict[str, object],
    ) -> dict[str, object]:
        return _calendar_list_calendars(state, arguments)


__all__ = ["ListCalendarsOperation"]
