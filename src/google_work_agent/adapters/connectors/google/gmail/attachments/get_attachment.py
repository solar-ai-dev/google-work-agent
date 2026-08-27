"""Canonical bounded Gmail attachment READ operation."""

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    provider_operation_runtime,
)


class GetAttachmentOperation(provider_operation_runtime.WorkspaceProviderOperation):
    tool_id = "gmail_get_attachment"


__all__ = ["GetAttachmentOperation"]
