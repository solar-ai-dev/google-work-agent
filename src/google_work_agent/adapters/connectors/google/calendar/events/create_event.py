"""Canonical Google provider operation for calendar create event."""

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    credential_provider as workspace_support,
)


def _calendar_create_event(
    state: workspace_support.GoogleWorkspaceCredentialProvider, arguments: dict[str, object]
) -> dict[str, object]:
    calendar_id = workspace_support._text_argument(arguments, "calendar_id", maximum=2048)
    payload = workspace_support._dict_argument(arguments, "payload")
    workspace_support._validate_claim_context(
        state,
        tool_name="calendar_create_event",
        claim_context=arguments.get("claim_context"),
        execution_arguments=workspace_support._execution_arguments(arguments),
    )
    body: dict[str, object] = {
        "summary": workspace_support._text_argument(payload, "title", maximum=1024),
        "start": {"dateTime": workspace_support._text_argument(payload, "start", maximum=64)},
        "end": {"dateTime": workspace_support._text_argument(payload, "end", maximum=64)},
    }
    description = workspace_support._optional_text(payload.get("description"))
    recovery_fingerprint = workspace_support._optional_text(payload.get("recovery_fingerprint"))
    if recovery_fingerprint:
        marker = workspace_support._recovery_marker(recovery_fingerprint)
        description = f"{description}\n\n{marker}" if description else marker
    if description:
        body["description"] = description
    attendees = workspace_support._calendar_attendees_argument(payload)
    if attendees is not None:
        body["attendees"] = attendees
    calendar_path = workspace_support.quote(calendar_id, safe="")
    response = workspace_support._google_api_post(
        state,
        f"https://www.googleapis.com/calendar/v3/calendars/{calendar_path}/events",
        body,
    )
    return {"item": workspace_support._event_snapshot(response, calendar_id)}


class CreateEventOperation:
    tool_id = "calendar_create_event"

    def execute(
        self,
        state: workspace_support.GoogleWorkspaceCredentialProvider,
        arguments: dict[str, object],
    ) -> dict[str, object]:
        return _calendar_create_event(state, arguments)


__all__ = ["CreateEventOperation"]
