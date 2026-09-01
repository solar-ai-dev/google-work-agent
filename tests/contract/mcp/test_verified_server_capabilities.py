from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from google_work_agent.adapters.connectors.google.workspace.composition import (
    build_google_workspace_connector_descriptor,
)
from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    credential_provider as workspace_tools,
)
from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    entrypoint as verified_server,
)
from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    project_registry,
)
from google_work_agent.adapters.connectors.runtime.stdio_mcp_client import MCPArtifactConfig
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)

build_google_workspace_internal_capabilities = (
    project_registry.build_google_workspace_internal_capabilities
)


def test_verified_server_declared_surface_maps_to_handlers() -> None:
    verified_server._validate_declared_surface()

    public_names = frozenset(entry.tool_name for entry in load_signed_tool_registry().entries)
    internal_names = frozenset(
        capability.tool_name for capability in build_google_workspace_internal_capabilities()
    )
    assert public_names.isdisjoint(internal_names)
    assert internal_names == {
        "gmail_get_ui_thread_detail",
        "search_by_recovery_fingerprint",
    }
    for name in public_names:
        assert verified_server.has_operation(name)
    for name in internal_names:
        assert verified_server.has_internal_operation(name)


def test_callable_legacy_helper_is_not_dispatch_authority() -> None:
    assert callable(workspace_tools._gmail_thread_list_metadata)
    state = cast(workspace_tools.GoogleWorkspaceCredentialProvider, object())

    with pytest.raises(workspace_tools._WorkspaceToolError) as captured:
        verified_server._tool_call(
            state,
            tool_name="gmail_thread_list_metadata",
            arguments={},
        )

    assert str(captured.value) == "TOOL_NOT_AVAILABLE"


def test_google_connector_uses_verified_server_for_default_module() -> None:
    descriptor = build_google_workspace_connector_descriptor(
        _artifact_config(),
        expected_tool_descriptors=tuple(
            load_signed_tool_registry().descriptor_expectations("google_workspace")
        ),
    )

    assert (
        descriptor.artifact_config.module_name
        == "google_work_agent.adapters.connectors.google.workspace.mcp_server.entrypoint"
    )


def test_google_connector_preserves_explicit_test_module() -> None:
    config = _artifact_config(module_name="tests.fakes.mcp_server")
    descriptor = build_google_workspace_connector_descriptor(
        config,
        expected_tool_descriptors=tuple(
            load_signed_tool_registry().descriptor_expectations("google_workspace")
        ),
    )

    assert descriptor.artifact_config.module_name == "tests.fakes.mcp_server"


DEFAULT_MCP_MODULE = "google_work_agent.adapters.connectors.google.workspace.mcp_server.entrypoint"


def _artifact_config(*, module_name: str = DEFAULT_MCP_MODULE) -> MCPArtifactConfig:
    return MCPArtifactConfig(
        executable_path=str(Path("python").resolve()),
        manifest_path=str(Path("manifest.json").resolve()),
        expected_binary_sha256="unused",
        expected_manifest_sha256="unused",
        expected_manifest_version="2026-08-07.p0",
        expected_protocol_version="2026-08-07.p0",
        expected_registry_manifest_hash=load_signed_tool_registry().entries_hash,
        startup_timeout_ms=1_000,
        request_timeout_ms=1_000,
        max_restart_count=1,
        environment="TEST",
        service_instance_id="svc-test",
        module_name=module_name,
    )
