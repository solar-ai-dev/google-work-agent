"""Canonical Gmail thread search connector operation."""

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    provider_operation_runtime,
)


class SearchThreadsOperation(provider_operation_runtime.WorkspaceProviderOperation):
    tool_id = "gmail_search_threads"
