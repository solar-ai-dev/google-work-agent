"""Google Workspace MCP credential-provider composition seam."""

from google_work_agent.adapters.connectors.google.workspace.mcp_server.workspace_runtime import (
    _WorkspaceState,
)


class GoogleWorkspaceCredentialProvider(_WorkspaceState):
    """Canonical owner of Google Workspace OAuth/provider process state."""


__all__ = ["GoogleWorkspaceCredentialProvider"]
