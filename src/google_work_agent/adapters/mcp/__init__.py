"""MCP child-process adapters."""

from google_work_agent.adapters.mcp.gateway import MCPGmailUiReadGateway, MCPGoogleWorkspaceGateway
from google_work_agent.adapters.mcp.oauth import MCPGoogleOAuthCredentialProvider
from google_work_agent.adapters.mcp.runtime import MCPRuntimeStatusProvider
from google_work_agent.adapters.mcp.transport import (
    MCPArtifactConfig,
    MCPManifestTool,
    MCPProcessStatus,
    MCPServerManifest,
    StaticArtifactSignatureVerifier,
    SubprocessMCPTransport,
    build_manifest_payload,
    calculate_file_sha256,
    normalize_manifest_bytes,
)

__all__ = [
    "MCPArtifactConfig",
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
