"""Google Workspace connector composition and compatibility surfaces."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from google_work_agent.adapters.connectors.runtime import (
    ConnectorMcpRuntime,
    RestartableMCPTransport,
)
from google_work_agent.adapters.mcp.capabilities import (
    build_google_workspace_internal_capabilities,
)
from google_work_agent.adapters.mcp.delivery_gateway import (
    DeliveryAwareMCPGoogleWorkspaceGateway,
)
from google_work_agent.adapters.mcp.delivery_transport import (
    DeliveryAwareSubprocessMCPTransport,
)
from google_work_agent.adapters.mcp.dispatch_contract import DispatchContractMCPTransport
from google_work_agent.adapters.mcp.gateway import (
    MCPGmailAttachmentGateway,
    MCPGmailUiReadGateway,
    MCPGoogleWorkspaceGateway,
)
from google_work_agent.adapters.mcp.manifest_guard import (
    ManifestEnforcedMCPTransport,
    RestartableManifestDelegate,
)
from google_work_agent.adapters.mcp.oauth import MCPGoogleOAuthCredentialProvider
from google_work_agent.adapters.mcp.transport import (
    MCPArtifactConfig,
    MCPConnectorDescriptor,
)
from google_work_agent.domain.google_workspace_tool_registry import (
    build_google_workspace_tool_registry,
)
from google_work_agent.domain.tool_registry import SignedToolRegistry
from google_work_agent.ports import MCPRuntimeMetadata, MCPTransport

GOOGLE_WORKSPACE_CONNECTOR_ID = "google_workspace"
_VERIFIED_MCP_MODULE_NAME = "google_work_agent.mcp.verified_server"
_LEGACY_MCP_MODULE_NAME = "google_work_agent.mcp.server"


def build_google_workspace_connector_descriptor(
    artifact_config: MCPArtifactConfig,
    *,
    tool_registry: SignedToolRegistry | None = None,
) -> MCPConnectorDescriptor:
    if artifact_config.module_name == _LEGACY_MCP_MODULE_NAME:
        artifact_config = replace(artifact_config, module_name=_VERIFIED_MCP_MODULE_NAME)
    return MCPConnectorDescriptor(
        connector_id=GOOGLE_WORKSPACE_CONNECTOR_ID,
        artifact_config=artifact_config,
        expected_tool_registry=tool_registry or build_google_workspace_tool_registry(),
    )


def _default_transport_factory(
    descriptor: MCPConnectorDescriptor,
) -> RestartableManifestDelegate:
    return DeliveryAwareSubprocessMCPTransport(descriptor=descriptor)


def _guarded_transport_factory(
    base_factory: Callable[[MCPConnectorDescriptor], RestartableManifestDelegate],
) -> Callable[[MCPConnectorDescriptor], RestartableMCPTransport]:
    """Wrap every connector transport in immutable-manifest and schema guards."""

    def build(descriptor: MCPConnectorDescriptor) -> RestartableMCPTransport:
        raw_delegate = base_factory(descriptor)
        try:
            manifest_guard = ManifestEnforcedMCPTransport(
                delegate=raw_delegate,
                descriptor=descriptor,
                expected_internal_capabilities=build_google_workspace_internal_capabilities(),
            )
            return DispatchContractMCPTransport(
                delegate=manifest_guard,
                descriptor=descriptor,
            )
        except Exception:
            raw_delegate.close()
            raise

    return build


class GoogleWorkspaceConnector:
    def __init__(
        self,
        *,
        descriptor: MCPConnectorDescriptor,
        transport_factory: (
            Callable[[MCPConnectorDescriptor], RestartableManifestDelegate] | None
        ) = None,
    ) -> None:
        if descriptor.connector_id != GOOGLE_WORKSPACE_CONNECTOR_ID:
            raise ValueError("Google Workspace connector descriptor id mismatch")
        base_factory = transport_factory or _default_transport_factory
        self._runtime = ConnectorMcpRuntime(
            descriptor=descriptor,
            transport_factory=_guarded_transport_factory(base_factory),
        )
        self._gateway: MCPGoogleWorkspaceGateway | None = None
        self._oauth_provider: MCPGoogleOAuthCredentialProvider | None = None
        self._gmail_ui_gateway: MCPGmailUiReadGateway | None = None
        self._gmail_attachment_gateway: MCPGmailAttachmentGateway | None = None

    @property
    def connector_id(self) -> str:
        return self._runtime.connector_id

    @property
    def descriptor(self) -> MCPConnectorDescriptor:
        return self._runtime.descriptor

    @property
    def transport(self) -> MCPTransport:
        return self._runtime.transport_for_diagnostics

    @property
    def workspace_gateway(self) -> MCPGoogleWorkspaceGateway:
        if self._gateway is None:
            raise RuntimeError("Google Workspace connector is not started")
        return self._gateway

    @property
    def oauth_provider(self) -> MCPGoogleOAuthCredentialProvider:
        if self._oauth_provider is None:
            raise RuntimeError("Google Workspace connector is not started")
        return self._oauth_provider

    @property
    def gmail_ui_gateway(self) -> MCPGmailUiReadGateway:
        if self._gmail_ui_gateway is None:
            raise RuntimeError("Google Workspace connector is not started")
        return self._gmail_ui_gateway

    @property
    def gmail_attachment_gateway(self) -> MCPGmailAttachmentGateway:
        if self._gmail_attachment_gateway is None:
            raise RuntimeError("Google Workspace connector is not started")
        return self._gmail_attachment_gateway

    def start(self) -> MCPTransport:
        transport = self._runtime.start()
        if self._gateway is None:
            self._gateway = DeliveryAwareMCPGoogleWorkspaceGateway(transport=transport)
            self._oauth_provider = MCPGoogleOAuthCredentialProvider(transport=transport)
            self._gmail_ui_gateway = MCPGmailUiReadGateway(transport=transport)
            self._gmail_attachment_gateway = MCPGmailAttachmentGateway(transport=transport)
        return transport

    def health(self) -> MCPRuntimeMetadata:
        return self._runtime.health()

    def restart(self) -> MCPRuntimeMetadata:
        return self._runtime.restart()

    def close(self) -> None:
        self._runtime.close()
        self._gateway = None
        self._oauth_provider = None
        self._gmail_ui_gateway = None
        self._gmail_attachment_gateway = None
