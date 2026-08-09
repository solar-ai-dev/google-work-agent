from __future__ import annotations

import json
import sys
from hashlib import sha256
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

import pytest

from google_work_agent.adapters.mcp import (
    MCPArtifactConfig,
    MCPGoogleOAuthCredentialProvider,
    MCPGoogleWorkspaceGateway,
    SubprocessMCPTransport,
    build_manifest_payload,
    calculate_file_sha256,
)
from google_work_agent.ports import GoogleWorkspaceErrorCode, GoogleWorkspaceGatewayError


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

        sent = gateway.send_gmail(
            draft_id="draft-followup",
            recovery_fingerprint="contract-send-fingerprint",
            claim_context=_claim_context(
                gateway=gateway,
                tool_name="gmail_send",
                arguments={"draft_id": "draft-followup"},
            ),
        )
        assert sent.resource_id == "sent-draft-followup"
        assert gateway.get_gmail_message(message_id=sent.resource_id).payload["sent"] is True

        deleted = gateway.delete_calendar_event(
            calendar_id="calendar-primary",
            event_id="event-focus",
            claim_context=_claim_context(
                gateway=gateway,
                tool_name="calendar_delete_event",
                arguments={"calendar_id": "calendar-primary", "event_id": "event-focus"},
            ),
        )
        assert deleted.payload == {"deleted": True}
        with pytest.raises(GoogleWorkspaceGatewayError) as error_info:
            gateway.get_calendar_event(calendar_id="calendar-primary", event_id="event-focus")
        assert error_info.value.code is GoogleWorkspaceErrorCode.NOT_FOUND

        runtime = transport.runtime_metadata()
        assert runtime.process_status == "READY"
        assert runtime.process_instance_id is not None
    finally:
        transport.close()


def _claim_context(
    *,
    gateway: MCPGoogleWorkspaceGateway,
    tool_name: str,
    arguments: dict[str, object],
) -> dict[str, object]:
    return gateway.prepare_claim_context(
        claim_payload={
            "action_id": f"action-{tool_name}",
            "approval_id": f"approval-{tool_name}",
            "attempt_id": f"attempt-{tool_name}",
            "service_instance_id": "svc-contract",
            "expires_at_ms": 4_102_444_800_000,
            "nonce": f"nonce-{tool_name}",
        },
        tool_name=tool_name,
        canonical_arguments_hash=sha256(
            json.dumps(arguments, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    )
