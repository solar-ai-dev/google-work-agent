from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from tests.support.mcp_manifest import build_manifest_payload

from google_work_agent.adapters.connectors.google.workspace.composition import (
    build_google_workspace_connector_descriptor,
)
from google_work_agent.adapters.connectors.runtime.connector_runtime_registry import (
    ConnectorRuntimeRegistry,
)
from google_work_agent.adapters.connectors.runtime.stdio_mcp_client import (
    MCPArtifactConfig,
    MCPServerManifest,
    StaticArtifactSignatureVerifier,
    StdioMCPClientAdapter,
    calculate_file_sha256,
)
from google_work_agent.application.tool_registry import load_signed_tool_registry
from google_work_agent.ports.connector.mcp_client_port import (
    MCPClientPortError,
    MCPClientPortErrorCode,
)
from google_work_agent.ports.system.artifact_signature_verifier import (
    ArtifactSignatureDecision,
)


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


def test_mcp_projection_rejects_duplicate_json_fields(tmp_path: Path) -> None:
    manifest_path = tmp_path / "mcp-manifest.json"
    manifest_path.write_text(
        '{"manifest_version":"2026-08-07.p0",'
        '"manifest_version":"2026-08-07.p0",'
        '"protocol_version":"2026-08-07.p0","connector_id":"google_workspace",'
        '"registry_manifest_hash":"x","tools":[]}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate MCP JSON field"):
        MCPServerManifest.load(manifest_path)


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


def test_installed_transport_executes_verified_binary_without_pythonpath_or_parent_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = (tmp_path / "GoogleWorkspaceMcpServer.exe").resolve()
    executable.write_bytes(b"installed-mcp")
    manifest_path = (tmp_path / "tool-descriptor-projection-v1.json").resolve()
    manifest_path.write_text(json.dumps(build_manifest_payload()), encoding="utf-8")
    registry = load_signed_tool_registry()
    captured: dict[str, object] = {}

    class _Process:
        pass

    def fake_popen(command: list[str], **kwargs: object) -> _Process:
        captured["command"] = command
        captured.update(kwargs)
        return _Process()

    monkeypatch.setenv("BOOTSTRAP_SECRET", "forbidden")
    monkeypatch.setenv("LLM_API_KEY", "forbidden")
    monkeypatch.setattr(
        "google_work_agent.adapters.connectors.runtime.stdio_mcp_client.subprocess.Popen",
        fake_popen,
    )
    monkeypatch.setattr(
        "google_work_agent.adapters.connectors.runtime.stdio_mcp_client.threading.Thread.start",
        lambda _thread: None,
    )
    monkeypatch.setattr(StdioMCPClientAdapter, "_perform_handshake", lambda _self: None)
    config = MCPArtifactConfig(
        executable_path=str(executable),
        manifest_path=str(manifest_path),
        expected_binary_sha256=calculate_file_sha256(executable),
        expected_manifest_sha256=calculate_file_sha256(manifest_path),
        expected_manifest_version="2026-08-07.p0",
        expected_protocol_version="2026-08-07.p0",
        expected_registry_manifest_hash=registry.entries_hash,
        startup_timeout_ms=5_000,
        request_timeout_ms=1_000,
        max_restart_count=1,
        environment="PRODUCTION",
        service_instance_id="service-1",
        module_name=None,
        working_directory=str(tmp_path),
        extra_environment={
            "GOOGLE_OAUTH_ENV": "PRODUCTION",
            "GOOGLE_OAUTH_CLIENT_ID": "client-id",
        },
    )
    client = StdioMCPClientAdapter(
        descriptor=build_google_workspace_connector_descriptor(
            config,
            expected_tool_descriptors=tuple(
                registry.descriptor_expectations("google_workspace")
            ),
        ),
        runtime_registry=ConnectorRuntimeRegistry(),
        signature_verifier=StaticArtifactSignatureVerifier(
            ArtifactSignatureDecision(allowed=True)
        ),
    )
    client._process = None

    child_environment = captured["env"]
    assert captured["command"] == [str(executable)]
    assert isinstance(child_environment, dict)
    assert "PYTHONPATH" not in child_environment
    assert "PATH" not in child_environment
    assert "BOOTSTRAP_SECRET" not in child_environment
    assert "LLM_API_KEY" not in child_environment
    assert child_environment["GOOGLE_OAUTH_ENV"] == "PRODUCTION"


def test_failed_handshake_terminates_spawned_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = tmp_path / "mcp-manifest.json"
    manifest_path.write_text(json.dumps(build_manifest_payload()), encoding="utf-8")
    registry = load_signed_tool_registry()

    class _FailedProcess:
        def __init__(self) -> None:
            self.killed = False
            self.waited = False

        def poll(self) -> None:
            return None

        def kill(self) -> None:
            self.killed = True

        def wait(self, *, timeout: int) -> int:
            assert timeout == 5
            self.waited = True
            return 1

    process = _FailedProcess()
    monkeypatch.setattr(
        "google_work_agent.adapters.connectors.runtime.stdio_mcp_client.subprocess.Popen",
        lambda *_args, **_kwargs: process,
    )
    monkeypatch.setattr(
        "google_work_agent.adapters.connectors.runtime.stdio_mcp_client.threading.Thread.start",
        lambda _thread: None,
    )

    def fail_handshake(_client: StdioMCPClientAdapter) -> None:
        raise MCPClientPortError(
            code=MCPClientPortErrorCode.HANDSHAKE_FAILED,
            message="fixture handshake failure",
        )

    monkeypatch.setattr(StdioMCPClientAdapter, "_perform_handshake", fail_handshake)

    with pytest.raises(MCPClientPortError):
        StdioMCPClientAdapter(
            descriptor=build_google_workspace_connector_descriptor(
                _config(manifest_path, registry.entries_hash),
                expected_tool_descriptors=tuple(
                    registry.descriptor_expectations("google_workspace")
                ),
            ),
            runtime_registry=ConnectorRuntimeRegistry(),
        )

    assert process.killed is True
    assert process.waited is True


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
