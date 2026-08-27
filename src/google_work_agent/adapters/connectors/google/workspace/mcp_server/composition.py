"""Construct Google Workspace MCP server state."""

from google_work_agent.adapters.connectors.google.workspace.mcp_server.credential_provider import (
    GoogleWorkspaceCredentialProvider,
)


class GoogleWorkspaceMcpServerComposition:
    """Construct the one credential/provider state used by the MCP child."""

    def compose(self) -> GoogleWorkspaceCredentialProvider:
        return GoogleWorkspaceCredentialProvider()


def compose_server_state() -> GoogleWorkspaceCredentialProvider:
    return GoogleWorkspaceMcpServerComposition().compose()


__all__ = ["GoogleWorkspaceMcpServerComposition", "compose_server_state"]
