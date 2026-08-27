"""Canonical Google Tasks delete connector operation."""

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    provider_operation_runtime,
)


class DeleteTaskOperation(provider_operation_runtime.WorkspaceProviderOperation):
    tool_id = "tasks_delete_task"
