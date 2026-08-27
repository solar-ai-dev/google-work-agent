"""Canonical Google Calendar list-calendars connector operation."""

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    provider_operation_runtime,
)


class ListCalendarsOperation(provider_operation_runtime.WorkspaceProviderOperation):
    tool_id = "calendar_list_calendars"
