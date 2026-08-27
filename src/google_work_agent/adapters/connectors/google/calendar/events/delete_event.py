"""Canonical Google Calendar event delete connector operation."""

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    provider_operation_runtime,
)


class DeleteEventOperation(provider_operation_runtime.WorkspaceProviderOperation):
    tool_id = "calendar_delete_event"
