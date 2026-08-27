"""Canonical Google Calendar free/busy connector operation."""

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    provider_operation_runtime,
)


class QueryFreebusyOperation(provider_operation_runtime.WorkspaceProviderOperation):
    tool_id = "calendar_query_freebusy"
