"""Connector adapter composition package."""

from google_work_agent.adapters.connectors.google_workspace import (
    GOOGLE_WORKSPACE_CONNECTOR_ID,
    GoogleWorkspaceConnector,
    build_google_workspace_connector_descriptor,
)
from google_work_agent.adapters.connectors.runtime import ConnectorMcpRuntime

__all__ = [
    "GOOGLE_WORKSPACE_CONNECTOR_ID",
    "ConnectorMcpRuntime",
    "GoogleWorkspaceConnector",
    "build_google_workspace_connector_descriptor",
]
