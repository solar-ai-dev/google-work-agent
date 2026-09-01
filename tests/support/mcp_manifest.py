from google_work_agent.adapters.connectors.runtime.stdio_mcp_client import (
    build_manifest_payload_for_descriptors,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)


def build_manifest_payload() -> dict[str, object]:
    registry = load_signed_tool_registry()
    return build_manifest_payload_for_descriptors(
        connector_id="google_workspace",
        registry_manifest_hash=registry.entries_hash,
        descriptors=tuple(registry.descriptor_expectations("google_workspace")),
    )
