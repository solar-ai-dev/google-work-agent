"""Canonical Google provider operation for calendar list events."""

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    credential_provider as workspace_support,
)


def _calendar_list_events(
    state: workspace_support.GoogleWorkspaceCredentialProvider, arguments: dict[str, object]
) -> dict[str, object]:
    calendar_id = workspace_support._text_argument(arguments, "calendar_id", maximum=2048)
    params = workspace_support._page_params(arguments)
    time_min = arguments.get("time_min")
    if time_min is not None:
        params["timeMin"] = workspace_support._text_value(time_min, maximum=64)
    time_max = arguments.get("time_max")
    if time_max is not None:
        params["timeMax"] = workspace_support._text_value(time_max, maximum=64)
    single_events = arguments.get("single_events")
    if single_events is not None:
        if not isinstance(single_events, bool):
            raise workspace_support._WorkspaceToolError("INVALID_ARGUMENT")
        params["singleEvents"] = "true" if single_events else "false"
    order_by = arguments.get("order_by")
    if order_by is not None:
        order_by_value = workspace_support._text_value(order_by, maximum=32)
        if order_by_value != "startTime" or single_events is not True:
            raise workspace_support._WorkspaceToolError("INVALID_ARGUMENT")
        params["orderBy"] = order_by_value
    calendar_path = workspace_support.quote(calendar_id, safe="")
    payload = workspace_support._google_api(
        state,
        f"https://www.googleapis.com/calendar/v3/calendars/{calendar_path}/events",
        params,
    )
    items = [
        workspace_support._event_snapshot(item, calendar_id)
        for item in workspace_support._object_list(payload.get("items"))
    ]
    return {
        "items": items,
        "next_page_token": workspace_support._optional_text(payload.get("nextPageToken")),
    }


class ListEventsOperation:
    tool_id = "calendar_list_events"

    def execute(
        self,
        state: workspace_support.GoogleWorkspaceCredentialProvider,
        arguments: dict[str, object],
    ) -> dict[str, object]:
        return _calendar_list_events(state, arguments)


__all__ = ["ListEventsOperation"]
