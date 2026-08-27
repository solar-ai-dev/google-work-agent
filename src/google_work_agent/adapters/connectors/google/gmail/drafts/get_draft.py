"""Canonical Gmail draft detail/verification connector operation."""

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    provider_operation_runtime,
)


class GetDraftOperation(provider_operation_runtime.WorkspaceProviderOperation):
    tool_id = "gmail_get_draft"
