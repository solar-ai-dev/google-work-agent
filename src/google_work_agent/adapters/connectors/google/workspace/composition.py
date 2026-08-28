"""Google Workspace owner-local connector runtime composition."""

from __future__ import annotations

from google_work_agent.adapters.connectors.runtime.connector_runtime_registry import (
    ConnectorRuntimeRegistry,
)
from google_work_agent.adapters.connectors.runtime.mcp_connector_read import (
    McpConnectorReadAdapter,
)
from google_work_agent.adapters.connectors.runtime.mcp_connector_write import (
    McpConnectorWriteAdapter,
)
from google_work_agent.adapters.connectors.runtime.mcp_oauth_credential import (
    McpOAuthCredentialAdapter,
)
from google_work_agent.adapters.connectors.runtime.stdio_mcp_client import (
    MCPArtifactConfig,
    MCPConnectorDescriptor,
    StdioMCPClientAdapter,
)
from google_work_agent.ports.connector.mcp_client_port import MCPToolDescriptorV1

GOOGLE_WORKSPACE_CONNECTOR_ID = "google_workspace"


def build_google_workspace_connector_descriptor(
    artifact_config: MCPArtifactConfig,
    *,
    expected_tool_descriptors: tuple[MCPToolDescriptorV1, ...],
) -> MCPConnectorDescriptor:
    return MCPConnectorDescriptor(
        connector_id=GOOGLE_WORKSPACE_CONNECTOR_ID,
        artifact_config=artifact_config,
        expected_tool_descriptors=expected_tool_descriptors,
    )


class GoogleWorkspaceConnector:
    """Own the one Google Workspace stdio child and its canonical adapters."""

    def __init__(
        self,
        *,
        descriptor: MCPConnectorDescriptor,
        runtime_registry: ConnectorRuntimeRegistry,
    ) -> None:
        if descriptor.connector_id != GOOGLE_WORKSPACE_CONNECTOR_ID:
            raise ValueError("Google Workspace connector descriptor id mismatch")
        self._descriptor = descriptor
        self._runtime_registry = runtime_registry
        self._client: StdioMCPClientAdapter | None = None

    @property
    def connector_id(self) -> str:
        return self._descriptor.connector_id

    @property
    def descriptor(self) -> MCPConnectorDescriptor:
        return self._descriptor

    @property
    def client(self) -> StdioMCPClientAdapter:
        if self._client is None:
            raise RuntimeError("Google Workspace connector is not started")
        return self._client

    @property
    def read_port(self) -> McpConnectorReadAdapter:
        return McpConnectorReadAdapter(
            runtime_registry=self._runtime_registry,
            mcp_client=self.client,
        )

    @property
    def write_port(self) -> McpConnectorWriteAdapter:
        return McpConnectorWriteAdapter(
            runtime_registry=self._runtime_registry,
            mcp_client=self.client,
        )

    @property
    def oauth_port(self) -> McpOAuthCredentialAdapter:
        return McpOAuthCredentialAdapter(
            runtime_registry=self._runtime_registry,
            mcp_client=self.client,
        )

    def start(self) -> StdioMCPClientAdapter:
        if self._client is None:
            self._client = StdioMCPClientAdapter(
                descriptor=self._descriptor,
                runtime_registry=self._runtime_registry,
            )
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None


__all__ = [
    "GOOGLE_WORKSPACE_CONNECTOR_ID",
    "GoogleWorkspaceConnector",
    "build_google_workspace_connector_descriptor",
]
