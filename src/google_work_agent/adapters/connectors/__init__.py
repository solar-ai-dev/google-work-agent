"""Connector adapter composition package."""

from google_work_agent.adapters.connectors.connector_mcp_runtime import ConnectorMcpRuntime
from google_work_agent.adapters.connectors.google_workspace import (
    GOOGLE_WORKSPACE_CONNECTOR_ID,
    GoogleWorkspaceConnector,
    build_google_workspace_connector_descriptor,
)
from google_work_agent.adapters.connectors.google_workspace_execution import (
    GoogleWorkspaceExecutionBackend,
)
from google_work_agent.adapters.connectors.google_workspace_reader import (
    GoogleWorkspaceConnectorReader,
)

__all__ = [
    "GOOGLE_WORKSPACE_CONNECTOR_ID",
    "ConnectorMcpRuntime",
    "GoogleWorkspaceConnector",
    "GoogleWorkspaceConnectorReader",
    "GoogleWorkspaceExecutionBackend",
    "build_google_workspace_connector_descriptor",
]
