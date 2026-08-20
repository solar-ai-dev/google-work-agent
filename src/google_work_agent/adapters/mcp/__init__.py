"""MCP child-process adapters."""

from google_work_agent.adapters.mcp.delivery_gateway import (
    DeliveryAwareMCPGoogleWorkspaceGateway as MCPGoogleWorkspaceGateway,
)
from google_work_agent.adapters.mcp.gateway import MCPGmailUiReadGateway
from google_work_agent.adapters.mcp.google_workspace_compat import (
    SubprocessMCPTransport,
    build_manifest_payload,
)
from google_work_agent.adapters.mcp.oauth import MCPGoogleOAuthCredentialProvider
from google_work_agent.adapters.mcp.runtime import MCPRuntimeStatusProvider
from google_work_agent.adapters.mcp.transport import (
    MCPArtifactConfig,
    MCPConnectorDescriptor,
    MCPManifestTool,
    MCPProcessStatus,
    MCPServerManifest,
    StaticArtifactSignatureVerifier,
    calculate_file_sha256,
    normalize_manifest_bytes,
)

__all__ = [
    "MCPArtifactConfig",
    "MCPConnectorDescriptor",
    "MCPGoogleOAuthCredentialProvider",
    "MCPGmailUiReadGateway",
    "MCPGoogleWorkspaceGateway",
    "MCPManifestTool",
    "MCPProcessStatus",
    "MCPRuntimeStatusProvider",
    "MCPServerManifest",
    "StaticArtifactSignatureVerifier",
    "SubprocessMCPTransport",
    "build_manifest_payload",
    "calculate_file_sha256",
    "normalize_manifest_bytes",
]
