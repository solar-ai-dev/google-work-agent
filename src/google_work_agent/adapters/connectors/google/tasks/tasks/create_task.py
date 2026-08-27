"""Canonical Google Tasks create connector operation."""

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    provider_operation_runtime,
)


class CreateTaskOperation(provider_operation_runtime.WorkspaceProviderOperation):
    tool_id = "tasks_create_task"
