"""Canonical Google Tasks detail/verification connector operation."""

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    provider_operation_runtime,
)


class GetTaskOperation(provider_operation_runtime.WorkspaceProviderOperation):
    tool_id = "tasks_get_task"
