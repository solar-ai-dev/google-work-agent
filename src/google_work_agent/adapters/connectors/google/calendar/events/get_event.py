"""Canonical Google Calendar event detail/verification connector operation."""

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    provider_operation_runtime,
)


class GetEventOperation(provider_operation_runtime.WorkspaceProviderOperation):
    tool_id = "calendar_get_event"
