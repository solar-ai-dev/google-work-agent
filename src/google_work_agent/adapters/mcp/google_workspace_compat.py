"""Compatibility entry points for the existing P0 Google MCP surface."""

from __future__ import annotations

from google_work_agent.adapters.mcp.capabilities import (
    INTERNAL_CAPABILITY_REGISTRY_VERSION,
    build_google_workspace_internal_capabilities,
)
from google_work_agent.adapters.mcp.transport import (
    MCPArtifactConfig,
    MCPConnectorDescriptor,
    build_manifest_payload_for_registry,
)
from google_work_agent.adapters.mcp.transport import (
    SubprocessMCPTransport as DescriptorSubprocessMCPTransport,
)
from google_work_agent.domain.google_workspace_tool_registry import (
    build_google_workspace_tool_registry,
)
from google_work_agent.ports import ArtifactSignatureVerifier


def build_manifest_payload() -> dict[str, object]:
    payload = build_manifest_payload_for_registry(build_google_workspace_tool_registry())
    capabilities = build_google_workspace_internal_capabilities()
    payload["internal_capability_registry_version"] = INTERNAL_CAPABILITY_REGISTRY_VERSION
    payload["internal_capabilities"] = [
        capability.to_manifest_payload() for capability in capabilities
    ]
    return payload


class SubprocessMCPTransport(DescriptorSubprocessMCPTransport):
    """Compatibility constructor for the original P0 Google transport surface."""

    def __init__(
        self,
        *,
        descriptor: MCPConnectorDescriptor | None = None,
        config: MCPArtifactConfig | None = None,
        signature_verifier: ArtifactSignatureVerifier | None = None,
    ) -> None:
        if descriptor is not None and config is not None:
            raise ValueError("provide either descriptor or config, not both")
        if descriptor is None:
            if config is None:
                raise ValueError("descriptor or config is required")
            descriptor = MCPConnectorDescriptor(
                connector_id="google_workspace",
                artifact_config=config,
                expected_tool_registry=build_google_workspace_tool_registry(),
            )
        super().__init__(
            descriptor=descriptor,
            signature_verifier=signature_verifier,
        )
