"""Canonical Google provider operation for calendar update event."""

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    credential_provider as workspace_support,
)


def _calendar_update_event(
    state: workspace_support.GoogleWorkspaceCredentialProvider, arguments: dict[str, object]
) -> dict[str, object]:
    calendar_id = workspace_support._text_argument(arguments, "calendar_id", maximum=2048)
    event_id = workspace_support._text_argument(arguments, "event_id", maximum=2048)
    payload = workspace_support._dict_argument(arguments, "payload")
    workspace_support._validate_claim_context(
        state,
        tool_name="calendar_update_event",
        claim_context=arguments.get("claim_context"),
        execution_arguments=workspace_support._execution_arguments(arguments),
    )
    body: dict[str, object] = {}
    if "title" in payload:
        body["summary"] = workspace_support._text_argument(
            payload, "title", maximum=1024, allow_empty=True
        )
    if "start" in payload:
        body["start"] = {"dateTime": workspace_support._text_argument(payload, "start", maximum=64)}
    if "end" in payload:
        body["end"] = {"dateTime": workspace_support._text_argument(payload, "end", maximum=64)}
    if "description" in payload:
        description = workspace_support._optional_text(payload.get("description"))
        if description:
            body["description"] = description
    attendees = workspace_support._calendar_attendees_argument(payload)
    if attendees is not None:
        body["attendees"] = attendees
    if not body:
        raise workspace_support._WorkspaceToolError("INVALID_ARGUMENT")
    calendar_path = workspace_support.quote(calendar_id, safe="")
    event_path = workspace_support.quote(event_id, safe="")
    response = workspace_support._google_api_call(
        state,
        "PATCH",
        f"https://www.googleapis.com/calendar/v3/calendars/{calendar_path}/events/{event_path}",
        body=body,
    )
    return {"item": workspace_support._event_snapshot(response, calendar_id)}


class UpdateEventOperation:
    tool_id = "calendar_update_event"

    def execute(
        self,
        state: workspace_support.GoogleWorkspaceCredentialProvider,
        arguments: dict[str, object],
    ) -> dict[str, object]:
        return _calendar_update_event(state, arguments)


__all__ = ["UpdateEventOperation"]
