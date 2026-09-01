from google_work_agent.adapters.connectors.google.workspace.mcp_server.project_registry import (
    project_registry,
    registry_manifest_hash,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)


def test_mcp_projection_is_exact_signed_registry_subset() -> None:
    registry = load_signed_tool_registry()
    expected = registry.descriptor_expectations("google_workspace")

    assert project_registry() == tuple(expected)
    assert registry_manifest_hash() == registry.entries_hash
