from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

from google_work_agent.adapters.mcp import (
    MCPArtifactConfig,
    MCPGoogleOAuthCredentialProvider,
    MCPGoogleWorkspaceGateway,
    SubprocessMCPTransport,
    build_manifest_payload,
    calculate_file_sha256,
)


def test_subprocess_transport_supports_oauth_and_google_tools(tmp_path: Path) -> None:
    manifest_path = tmp_path / "mcp-manifest.json"
    manifest_path.write_text(json.dumps(build_manifest_payload(), sort_keys=True), encoding="utf-8")
    keyring_path = tmp_path / "test-keyring.json"
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
            service_instance_id="svc-contract",
            working_directory=str(Path(__file__).resolve().parents[3]),
            extra_environment={
                "GWA_TEST_KEYRING_PATH": str(keyring_path.resolve()),
                "GWA_PRODUCT_FIXTURE_MANIFEST": str(fixture_manifest.resolve()),
            },
        )
    )
    provider = MCPGoogleOAuthCredentialProvider(transport=transport)
    gateway = MCPGoogleWorkspaceGateway(transport=transport)
    try:
        before = provider.get_connection_status()
        assert before.connected is False

        start = provider.start_oauth()
        state = parse_qs(urlparse(start.authorization_url).query)["state"][0]
        with urlopen(f"{start.callback_url}?state={state}&code=CANARY_AUTH_CODE") as response:
            assert response.status == 200

        connected = provider.get_connection_status()
        assert connected.connected is True
        assert connected.account_email == "user@example.com"

        page = gateway.search_gmail_threads(query="project", page_token=None, page_size=10)
        assert page.items
        assert page.items[0].resource_type.value == "gmail_thread"

        runtime = transport.runtime_metadata()
        assert runtime.process_status == "READY"
        assert runtime.process_instance_id is not None
    finally:
        transport.close()
