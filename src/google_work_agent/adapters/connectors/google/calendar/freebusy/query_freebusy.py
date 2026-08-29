"""Canonical Google provider operation for calendar query freebusy."""

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    credential_provider as workspace_support,
)
from google_work_agent.ports.connector.contracts.google_workspace import TimeRange


def _calendar_query_freebusy(
    state: workspace_support.GoogleWorkspaceCredentialProvider, arguments: dict[str, object]
) -> dict[str, object]:
    calendar_ids = workspace_support._calendar_ids_argument(arguments)
    try:
        time_range = TimeRange(
            start=workspace_support._text_argument(arguments, "time_min", maximum=2048),
            end=workspace_support._text_argument(arguments, "time_max", maximum=2048),
        )
    except ValueError as error:
        raise workspace_support._WorkspaceToolError("INVALID_ARGUMENT") from error
    payload = workspace_support._google_api_post(
        state,
        "https://www.googleapis.com/calendar/v3/freeBusy",
        {
            "timeMin": time_range.start,
            "timeMax": time_range.end,
            "items": [{"id": calendar_id} for calendar_id in calendar_ids],
        },
    )
    calendars = workspace_support.cast(dict[str, object], payload.get("calendars") or {})
    return {
        "calendars": [
            {
                "calendar_id": calendar_id,
                "intervals": [
                    {
                        "start": workspace_support._required_response_text(interval, "start"),
                        "end": workspace_support._required_response_text(interval, "end"),
                        "transparency": "busy",
                    }
                    for interval in workspace_support._object_list(
                        workspace_support.cast(
                            dict[str, object], calendars.get(calendar_id) or {}
                        ).get("busy")
                    )
                ],
            }
            for calendar_id in calendar_ids
        ]
    }


class QueryFreebusyOperation:
    tool_id = "calendar_query_freebusy"

    def execute(
        self,
        state: workspace_support.GoogleWorkspaceCredentialProvider,
        arguments: dict[str, object],
    ) -> dict[str, object]:
        return _calendar_query_freebusy(state, arguments)


__all__ = ["QueryFreebusyOperation"]
