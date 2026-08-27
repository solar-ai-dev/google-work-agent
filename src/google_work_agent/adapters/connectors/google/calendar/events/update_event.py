"""Canonical Google Calendar event update connector operation."""

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    provider_operation_runtime,
)


class UpdateEventOperation(provider_operation_runtime.WorkspaceProviderOperation):
    tool_id = "calendar_update_event"
