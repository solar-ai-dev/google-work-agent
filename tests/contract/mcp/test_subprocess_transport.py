from __future__ import annotations

import json
import sys
from pathlib import Path

from google_work_agent.adapters.mcp import (
    MCPArtifactConfig,
    MCPGoogleOAuthCredentialProvider,
    SubprocessMCPTransport,
    build_manifest_payload,
    calculate_file_sha256,
)


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
