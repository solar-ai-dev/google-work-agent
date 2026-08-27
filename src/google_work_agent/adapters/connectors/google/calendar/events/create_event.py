"""Canonical Google Calendar event create connector operation."""

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    provider_operation_runtime,
)


class CreateEventOperation(provider_operation_runtime.WorkspaceProviderOperation):
    tool_id = "calendar_create_event"
