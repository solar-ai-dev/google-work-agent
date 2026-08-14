from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from google_work_agent.adapters.connectors import build_google_workspace_connector_descriptor
from google_work_agent.adapters.mcp import (
    MCPArtifactConfig,
    MCPGoogleOAuthCredentialProvider,
    SubprocessMCPTransport,
    build_manifest_payload,
    calculate_file_sha256,
)
from google_work_agent.domain import SignedToolRegistry
from google_work_agent.ports import MCPTransportError, MCPTransportErrorCode


def test_subprocess_transport_handshakes_without_fixture_google_tools(tmp_path: Path) -> None:
    manifest_path = tmp_path / "mcp-manifest.json"
    manifest_path.write_text(json.dumps(build_manifest_payload(), sort_keys=True), encoding="utf-8")
    executable = Path(sys.executable).resolve()
    transport = SubprocessMCPTransport(
        config=MCPArtifactConfig(
            executable_path=str(executable),
            manifest_path=str(manifest_path.resolve()),
            expected_binary_sha256=calculate_file_sha256(executable),
            expected_manifest_sha256=calculate_file_sha256(manifest_path.resolve()),
            expected_manifest_version="2026-08-07.p0",
            expected_protocol_version="2026-08-07.p0",
            expected_tool_registry_version="2026-08-06.p0",
            startup_timeout_ms=5_000,
            request_timeout_ms=5_000,
            max_restart_count=1,
            environment="DEVELOPMENT",
            service_instance_id="svc-contract",
            working_directory=str(Path(__file__).resolve().parents[3]),
            module_name="tests.fakes.mcp_server",
            extra_environment={"GOOGLE_OAUTH_CLIENT_ID": "test-desktop-client-id"},
        )
    )
    provider = MCPGoogleOAuthCredentialProvider(transport=transport)
    try:
        assert provider.get_connection_status().connected is False
        runtime = transport.runtime_metadata()
        assert runtime.process_status == "READY"
        assert runtime.process_instance_id is not None
    finally:
        transport.close()


def test_subprocess_transport_rejects_manifest_version_mismatch(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path)
    descriptor = build_google_workspace_connector_descriptor(
        _artifact_config(manifest_path, expected_manifest_version="unexpected")
    )

    with pytest.raises(MCPTransportError) as captured:
        SubprocessMCPTransport(descriptor=descriptor)

    assert captured.value.code is MCPTransportErrorCode.SCHEMA_MISMATCH


def test_subprocess_transport_rejects_manifest_registry_mismatch(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path)
    descriptor = build_google_workspace_connector_descriptor(_artifact_config(manifest_path))
    descriptor = replace(descriptor, expected_tool_registry=SignedToolRegistry(()))

    with pytest.raises(MCPTransportError) as captured:
        SubprocessMCPTransport(descriptor=descriptor)

    assert captured.value.code is MCPTransportErrorCode.TOOL_REJECTED


def test_subprocess_transport_rejects_tool_schema_mismatch(tmp_path: Path) -> None:
    payload = build_manifest_payload()
    tools = payload["tools"]
    assert isinstance(tools, list)
    first_tool = tools[0]
    assert isinstance(first_tool, dict)
    first_tool["tool_schema_hash"] = "mismatch"
    manifest_path = tmp_path / "mcp-manifest.json"
    manifest_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    descriptor = build_google_workspace_connector_descriptor(_artifact_config(manifest_path))

    with pytest.raises(MCPTransportError) as captured:
        SubprocessMCPTransport(descriptor=descriptor)

    assert captured.value.code is MCPTransportErrorCode.TOOL_REJECTED


def test_subprocess_transport_restarts_once_after_child_process_exit(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path)
    transport = SubprocessMCPTransport(config=_artifact_config(manifest_path))
    process = transport._process  # noqa: SLF001 - contract test forces the child-exit boundary
    assert process is not None
    process.kill()
    process.wait(timeout=5)

    try:
        provider = MCPGoogleOAuthCredentialProvider(transport=transport)
        assert provider.get_connection_status().connected is False
        metadata = transport.runtime_metadata()
        assert metadata.process_status == "READY"
        assert metadata.restart_count == 1
    finally:
        transport.close()


def _write_manifest(tmp_path: Path) -> Path:
    manifest_path = tmp_path / "mcp-manifest.json"
    manifest_path.write_text(json.dumps(build_manifest_payload(), sort_keys=True), encoding="utf-8")
    return manifest_path


def _artifact_config(
    manifest_path: Path,
    *,
    expected_manifest_version: str = "2026-08-07.p0",
) -> MCPArtifactConfig:
    executable = Path(sys.executable).resolve()
    return MCPArtifactConfig(
        executable_path=str(executable),
        manifest_path=str(manifest_path.resolve()),
        expected_binary_sha256=calculate_file_sha256(executable),
        expected_manifest_sha256=calculate_file_sha256(manifest_path.resolve()),
        expected_manifest_version=expected_manifest_version,
        expected_protocol_version="2026-08-07.p0",
        expected_tool_registry_version="2026-08-06.p0",
        startup_timeout_ms=5_000,
        request_timeout_ms=5_000,
        max_restart_count=1,
        environment="DEVELOPMENT",
        service_instance_id="svc-contract",
        working_directory=str(Path(__file__).resolve().parents[3]),
        module_name="tests.fakes.mcp_server",
    )
