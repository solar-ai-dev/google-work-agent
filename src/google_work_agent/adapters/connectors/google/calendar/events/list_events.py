"""Canonical Google Calendar event-list connector operation."""

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    provider_operation_runtime,
)


class ListEventsOperation(provider_operation_runtime.WorkspaceProviderOperation):
    tool_id = "calendar_list_events"
