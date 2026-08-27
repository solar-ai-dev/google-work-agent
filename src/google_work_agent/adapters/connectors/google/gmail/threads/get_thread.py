"""Canonical Gmail thread detail connector operation."""

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    provider_operation_runtime,
)


class GetThreadOperation(provider_operation_runtime.WorkspaceProviderOperation):
    tool_id = "gmail_get_thread"
