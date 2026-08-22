from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from google_work_agent.adapters.connectors.google_workspace import (
    build_google_workspace_connector_descriptor,
)
from google_work_agent.adapters.mcp import MCPArtifactConfig
from google_work_agent.adapters.mcp.capabilities import (
    build_google_workspace_internal_capabilities,
)
from google_work_agent.domain import build_p0_tool_registry
from google_work_agent.adapters.connectors.google.mcp import workspace_tools
from google_work_agent.adapters.connectors.google.mcp import verified_server


def test_verified_server_declared_surface_maps_to_handlers() -> None:
    verified_server._validate_declared_surface()  # noqa: SLF001

    public_names = frozenset(entry.tool_name for entry in build_p0_tool_registry().list_entries())
    internal_names = frozenset(
        capability.tool_name for capability in build_google_workspace_internal_capabilities()
    )
    assert public_names.isdisjoint(internal_names)
    assert internal_names == {
        "gmail_get_attachment",
        "gmail_get_ui_thread_detail",
        "search_by_recovery_fingerprint",
    }
    for name in public_names | internal_names:
        assert callable(verified_server._handler_for(name))  # noqa: SLF001


def test_callable_legacy_helper_is_not_dispatch_authority() -> None:
    assert callable(workspace_tools._gmail_thread_list_metadata)  # noqa: SLF001
    state = cast(workspace_tools._WorkspaceState, object())  # noqa: SLF001

    with pytest.raises(workspace_tools._WorkspaceToolError) as captured:  # noqa: SLF001
        verified_server._tool_call(  # noqa: SLF001
            state,
            tool_name="gmail_thread_list_metadata",
            arguments={},
        )

    assert str(captured.value) == "TOOL_NOT_AVAILABLE"


def test_google_connector_uses_verified_server_for_default_module() -> None:
    descriptor = build_google_workspace_connector_descriptor(_artifact_config())

    assert (
        descriptor.artifact_config.module_name
        == "google_work_agent.adapters.connectors.google.mcp.verified_server"
    )


def test_google_connector_preserves_explicit_test_module() -> None:
    config = _artifact_config(module_name="tests.fakes.mcp_server")
    descriptor = build_google_workspace_connector_descriptor(config)

    assert descriptor.artifact_config.module_name == "tests.fakes.mcp_server"


def _artifact_config(
    *,
    module_name: str = "google_work_agent.adapters.connectors.google.mcp.verified_server",
) -> MCPArtifactConfig:
    return MCPArtifactConfig(
        executable_path=str(Path("python").resolve()),
        manifest_path=str(Path("manifest.json").resolve()),
        expected_binary_sha256="unused",
        expected_manifest_sha256="unused",
        expected_manifest_version="2026-08-07.p0",
        expected_protocol_version="2026-08-07.p0",
        expected_tool_registry_version="2026-08-06.p0",
        startup_timeout_ms=1_000,
        request_timeout_ms=1_000,
        max_restart_count=1,
        environment="TEST",
        service_instance_id="svc-test",
        module_name=module_name,
    )
