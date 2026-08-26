"""MCP child-process adapters."""

from google_work_agent.adapters.connectors.runtime.stdio_mcp_client import (
    MCPArtifactConfig,
    MCPConnectorDescriptor,
    MCPManifestTool,
    MCPProcessStatus,
    MCPServerManifest,
    StaticArtifactSignatureVerifier,
    calculate_file_sha256,
    normalize_manifest_bytes,
)
from google_work_agent.adapters.mcp.delivery_gateway import (
    DeliveryAwareMCPGoogleWorkspaceGateway as MCPGoogleWorkspaceGateway,
)
from google_work_agent.adapters.mcp.gateway import MCPGmailUiReadGateway
from google_work_agent.adapters.mcp.google_workspace_compat import (
    StdioMCPClientAdapter,
    build_manifest_payload,
)
from google_work_agent.adapters.mcp.stdio_transport import MCPRuntimeStatusProvider

__all__ = [
    "MCPArtifactConfig",
    "MCPConnectorDescriptor",
    "MCPGmailUiReadGateway",
    "MCPGoogleWorkspaceGateway",
    "MCPManifestTool",
    "MCPProcessStatus",
    "MCPRuntimeStatusProvider",
    "MCPServerManifest",
    "StaticArtifactSignatureVerifier",
    "StdioMCPClientAdapter",
    "build_manifest_payload",
    "calculate_file_sha256",
    "normalize_manifest_bytes",
]
