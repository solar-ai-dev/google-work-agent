from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from tests.support.mcp_manifest import build_manifest_payload

from google_work_agent.adapters.connectors.google_workspace import (
    build_google_workspace_connector_descriptor,
)
from google_work_agent.adapters.connectors.runtime.connector_runtime_registry import (
    ConnectorRuntimeRegistry,
)
from google_work_agent.adapters.connectors.runtime.stdio_mcp_client import (
    MCPArtifactConfig,
    StdioMCPClientAdapter,
    calculate_file_sha256,
)
from google_work_agent.application.tool_registry import load_signed_tool_registry
from google_work_agent.ports import MCPClientPortError


def test_subprocess_transport_handshakes_and_projects_exact_tools(tmp_path) -> None:
    manifest_path = tmp_path / "mcp-manifest.json"
    manifest_path.write_text(json.dumps(build_manifest_payload(), sort_keys=True), encoding="utf-8")
    registry = load_signed_tool_registry()
    runtime_registry = ConnectorRuntimeRegistry()
    transport = StdioMCPClientAdapter(
        descriptor=build_google_workspace_connector_descriptor(
            _config(manifest_path, registry.entries_hash),
            expected_tool_descriptors=tuple(registry.descriptor_expectations("google_workspace")),
        ),
        runtime_registry=runtime_registry,
    )
    try:
        assert {tool.tool_id for tool in transport.list_tools("google_workspace")} == {
            entry.tool_id for entry in registry.entries
        }
        call_result = transport.call_tool(
            "google_workspace", "gmail_get_thread", {"thread_id": "thread-1"}, 1_000
        )
        assert call_result.transport_status == "OK"
        restart_result = transport.restart_once("google_workspace")
        assert restart_result.restarted is True
        assert transport.runtime_metadata().restart_count == 1
        assert transport.runtime_metadata().process_status == "READY"
    finally:
        transport.close()


def test_subprocess_transport_rejects_manifest_hash_mismatch(tmp_path) -> None:
    manifest_path = tmp_path / "mcp-manifest.json"
    manifest_path.write_text(json.dumps(build_manifest_payload()), encoding="utf-8")
    registry = load_signed_tool_registry()
    config = _config(manifest_path, registry.entries_hash)
    config = replace(config, expected_manifest_sha256="0" * 64)

    with pytest.raises(MCPClientPortError):
        StdioMCPClientAdapter(
            descriptor=build_google_workspace_connector_descriptor(
                config,
                expected_tool_descriptors=tuple(
                    registry.descriptor_expectations("google_workspace")
                ),
            ),
            runtime_registry=ConnectorRuntimeRegistry(),
        )


def test_subprocess_transport_preserves_server_delivery_certainty(tmp_path) -> None:
    manifest_path = tmp_path / "mcp-manifest.json"
    manifest_path.write_text(json.dumps(build_manifest_payload()), encoding="utf-8")
    registry = load_signed_tool_registry()
    transport = StdioMCPClientAdapter(
        descriptor=build_google_workspace_connector_descriptor(
            _config(manifest_path, registry.entries_hash),
            expected_tool_descriptors=tuple(registry.descriptor_expectations("google_workspace")),
        ),
        runtime_registry=ConnectorRuntimeRegistry(),
    )
    try:
        result = transport.call_tool(
            "google_workspace",
            "gmail_send",
            {"__test_delivery_certainty": "SENT_RESPONSE_LOST"},
            1_000,
        )
        assert result.transport_status == "ERROR"
        assert result.payload["delivery_certainty"] == "SENT_RESPONSE_LOST"
    finally:
        transport.close()


def _config(manifest_path: Path, registry_hash: str) -> MCPArtifactConfig:
    executable = str(sys.executable)
    return MCPArtifactConfig(
        executable_path=executable,
        manifest_path=str(manifest_path),
        expected_binary_sha256=calculate_file_sha256(Path(executable)),
        expected_manifest_sha256=calculate_file_sha256(manifest_path),
        expected_manifest_version="2026-08-07.p0",
        expected_protocol_version="2026-08-07.p0",
        expected_registry_manifest_hash=registry_hash,
        startup_timeout_ms=5_000,
        request_timeout_ms=1_000,
        max_restart_count=1,
        environment="TEST",
        service_instance_id="service-1",
        module_name="tests.fakes.mcp_server",
    )
