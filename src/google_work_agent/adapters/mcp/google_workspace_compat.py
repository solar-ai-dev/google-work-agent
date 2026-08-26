"""Compatibility entry points for the existing P0 Google MCP surface."""

from __future__ import annotations

from google_work_agent.adapters.mcp.capabilities import (
    INTERNAL_CAPABILITY_REGISTRY_VERSION,
    build_google_workspace_internal_capabilities,
)
from google_work_agent.adapters.mcp.delivery_transport import (
    DeliveryAwareStdioMCPClientAdapter,
)
from google_work_agent.adapters.connectors.runtime.stdio_mcp_client import (
    MCPArtifactConfig,
    MCPConnectorDescriptor,
    build_manifest_payload_for_registry,
)
from google_work_agent.domain.google_workspace_tool_contracts import (
    google_workspace_tool_contract,
)
from google_work_agent.domain.google_workspace_tool_registry import (
    build_google_workspace_tool_registry,
)
from google_work_agent.ports import ArtifactSignatureVerifier


def build_manifest_payload() -> dict[str, object]:
    registry = build_google_workspace_tool_registry()
    payload = build_manifest_payload_for_registry(registry)
    raw_tools = payload.get("tools")
    if not isinstance(raw_tools, list):
        raise RuntimeError("MCP manifest builder produced an invalid public tool surface")
    for item in raw_tools:
        if not isinstance(item, dict):
            raise RuntimeError("MCP manifest builder produced an invalid tool entry")
        tool_name = str(item.get("tool_name", ""))
        item.update(google_workspace_tool_contract(tool_name).manifest_schema_payload())

    capabilities = build_google_workspace_internal_capabilities()
    payload["internal_capability_registry_version"] = INTERNAL_CAPABILITY_REGISTRY_VERSION
    payload["internal_capabilities"] = [
        capability.to_manifest_payload() for capability in capabilities
    ]
    return payload


class StdioMCPClientAdapter(DeliveryAwareStdioMCPClientAdapter):
    """Compatibility constructor with canonical delivery-certainty parsing."""

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
