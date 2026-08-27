"""Canonical Google Tasks task-list connector operation."""

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    provider_operation_runtime,
)


class ListTasklistsOperation(provider_operation_runtime.WorkspaceProviderOperation):
    tool_id = "tasks_list_tasklists"
