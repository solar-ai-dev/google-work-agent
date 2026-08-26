from __future__ import annotations

from typing import Any

import pytest

from google_work_agent.adapters.mcp.gateway import MCPGoogleWorkspaceGateway
from google_work_agent.ports import (
    GoogleWorkspaceErrorCode,
    GoogleWorkspaceGatewayError,
    MCPControlResponse,
    MCPRuntimeMetadata,
    MCPToolResponse,
    MCPClientPortError,
    MCPClientPortErrorCode,
    ResourceType,
)


class _RecordingTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def call_tool(self, *, tool_name: str, arguments: dict[str, Any]) -> MCPToolResponse:
        self.calls.append((tool_name, dict(arguments)))
        item = {
            "fixture_snapshot_id": f"snapshot-{len(self.calls)}",
            "resource_type": "gmail_message",
            "resource_id": "message-1",
            "parent_id": None,
            "related_resource_ids": [],
            "version": "v1",
            "recovery_fingerprint": arguments.get("recovery_fingerprint"),
            "payload": {},
        }
        payload: dict[str, Any]
        if tool_name == "search_by_recovery_fingerprint":
            payload = {"items": [item]}
        else:
            payload = {"item": item}
        return MCPToolResponse(payload=payload, request_id=f"req-{len(self.calls)}")

    def call_control(
        self, *, method: str, arguments: dict[str, Any]
    ) -> MCPControlResponse:
        del method, arguments
        return MCPControlResponse(payload={}, request_id="req-control")

    def runtime_metadata(self) -> MCPRuntimeMetadata:
        return MCPRuntimeMetadata(
            process_status="READY",
            protocol_version="v1",
            manifest_version="v1",
            tool_registry_version="v1",
            available_tool_count=1,
            last_safe_error_code=None,
            restart_count=0,
            process_instance_id="mcp-1",
        )

    def close(self) -> None:
        return None


class _UnavailableTransport(_RecordingTransport):
    def call_tool(self, *, tool_name: str, arguments: dict[str, Any]) -> MCPToolResponse:
        self.calls.append((tool_name, dict(arguments)))
        raise MCPClientPortError(
            code=MCPClientPortErrorCode.PROCESS_UNAVAILABLE,
            message="mcp unavailable",
        )


def test_write_verification_and_recovery_reads_all_cross_mcp_transport() -> None:
    transport = _RecordingTransport()
    gateway = MCPGoogleWorkspaceGateway(transport=transport)

    written = gateway.send_gmail(
        draft_id="draft-1",
        recovery_fingerprint="rfp-1",
        claim_context=None,
    )
    verified = gateway.get_gmail_message(message_id="message-1")
    recovered = gateway.search_by_recovery_fingerprint(
        resource_type=ResourceType.GMAIL_MESSAGE,
        recovery_fingerprint="rfp-1",
    )

    assert written.resource_id == "message-1"
    assert verified.resource_id == "message-1"
    assert recovered[0].resource_id == "message-1"
    assert [name for name, _ in transport.calls] == [
        "gmail_send",
        "gmail_get_message",
        "search_by_recovery_fingerprint",
    ]


def test_mcp_unavailable_fails_closed_without_provider_fallback() -> None:
    transport = _UnavailableTransport()
    gateway = MCPGoogleWorkspaceGateway(transport=transport)

    with pytest.raises(GoogleWorkspaceGatewayError) as captured:
        gateway.send_gmail(
            draft_id="draft-1",
            recovery_fingerprint="rfp-1",
            claim_context=None,
        )

    assert captured.value.code is GoogleWorkspaceErrorCode.CONNECTION_CLOSED
    assert transport.calls == [
        (
            "gmail_send",
            {
                "draft_id": "draft-1",
                "recovery_fingerprint": "rfp-1",
                "claim_context": None,
            },
        )
    ]
