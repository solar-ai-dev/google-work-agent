from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

import pytest

from google_work_agent.adapters.mcp import (
    MCPArtifactConfig,
    MCPGoogleOAuthCredentialProvider,
    SubprocessMCPTransport,
    build_manifest_payload,
    calculate_file_sha256,
)
from google_work_agent.ports.mcp_transport import MCPTransportError, MCPTransportErrorCode


def test_mcp_oauth_flow_uses_loopback_callback_and_no_token_leakage(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(build_manifest_payload(), sort_keys=True), encoding="utf-8")
    fixture_manifest = (
        Path(__file__).resolve().parents[2] / "fixtures" / "product" / "manifest.json"
    )
    keyring_path = tmp_path / "keyring.json"
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
            service_instance_id="svc-oauth-contract",
            working_directory=str(Path(__file__).resolve().parents[3]),
            extra_environment={
                "GWA_TEST_KEYRING_PATH": str(keyring_path.resolve()),
                "GWA_PRODUCT_FIXTURE_MANIFEST": str(fixture_manifest.resolve()),
                "GOOGLE_OAUTH_CLIENT_ID": "test-desktop-client-id",
            },
        )
    )
    provider = MCPGoogleOAuthCredentialProvider(transport=transport)
    try:
        started = provider.start_oauth()
        assert started.callback_url.startswith("http://127.0.0.1:")
        assert "localhost" not in started.callback_url
        assert "test-desktop-client-id" not in started.authorization_url
        assert "refresh" not in started.authorization_url.lower()
        assert "access" not in started.authorization_url.lower()

        state = parse_qs(urlparse(started.authorization_url).query)["state"][0]
        with urlopen(f"{started.callback_url}?state={state}&code=CANARY_AUTH_CODE") as response:
            assert response.status == 200

        connected = provider.get_connection_status()
        assert connected.connected is True
        assert "CANARY_AUTH_CODE" not in repr(connected)
    finally:
        transport.close()


def test_mcp_oauth_start_rejects_missing_client_id_without_leaking_configuration(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(build_manifest_payload(), sort_keys=True), encoding="utf-8")
    fixture_manifest = (
        Path(__file__).resolve().parents[2] / "fixtures" / "product" / "manifest.json"
    )
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
            service_instance_id="svc-oauth-missing-config",
            working_directory=str(Path(__file__).resolve().parents[3]),
            extra_environment={
                "GWA_TEST_KEYRING_PATH": str((tmp_path / "keyring.json").resolve()),
                "GWA_PRODUCT_FIXTURE_MANIFEST": str(fixture_manifest.resolve()),
                "GOOGLE_OAUTH_CLIENT_ID": "",
            },
        )
    )
    provider = MCPGoogleOAuthCredentialProvider(transport=transport)
    try:
        with pytest.raises(MCPTransportError) as error_info:
            provider.start_oauth()

        assert error_info.value.code is MCPTransportErrorCode.CONFIGURATION_ERROR
        assert "GOOGLE_OAUTH_CLIENT_ID" in str(error_info.value)
        assert "client-id" not in str(error_info.value).lower()
    finally:
        transport.close()
