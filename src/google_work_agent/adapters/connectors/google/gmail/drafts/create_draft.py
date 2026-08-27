"""Canonical Gmail draft create connector operation."""

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    provider_operation_runtime,
)


class CreateDraftOperation(provider_operation_runtime.WorkspaceProviderOperation):
    tool_id = "gmail_create_draft"
