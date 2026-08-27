"""Canonical Google Tasks list connector operation."""

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    provider_operation_runtime,
)


class ListTasksOperation(provider_operation_runtime.WorkspaceProviderOperation):
    tool_id = "tasks_list_tasks"
