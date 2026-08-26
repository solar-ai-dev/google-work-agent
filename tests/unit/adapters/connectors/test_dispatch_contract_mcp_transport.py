from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from google_work_agent.adapters.connectors.google_workspace import (
    build_google_workspace_connector_descriptor,
)
from google_work_agent.adapters.mcp import (
    MCPArtifactConfig,
    build_manifest_payload,
    calculate_file_sha256,
)
from google_work_agent.adapters.mcp.dispatch_contract import DispatchContractMCPClientPort
from google_work_agent.adapters.mcp.manifest_guard import ManifestEnforcedMCPClientPort
from google_work_agent.ports import (
    DeliveryCertainty,
    MCPControlResponse,
    MCPRuntimeMetadata,
    MCPToolResponse,
    MCPClientPortError,
    MCPClientPortErrorCode,
)


class _FakeManifestGuard:
    def __init__(self) -> None:
        self.tool_calls: list[tuple[str, dict[str, object]]] = []
        self.responses: dict[str, dict[str, object]] = {
            "gmail_get_thread": _snapshot_envelope("gmail_thread", "thread-1"),
            "tasks_create_task": _snapshot_envelope("task", "task-1", parent_id="list-1"),
            "gmail_get_attachment": {
                "message_id": "message-1",
                "attachment_id": "attachment-1",
                "size_bytes": 3,
                "sha256": "abc",
                "data_base64url": "YWJj",
            },
        }

    @property
    def service_instance_id(self) -> str:
        return "svc-test"

    @property
    def process_instance_id(self) -> str | None:
        return "mcp-test"

    def sign_claim_context(self, payload: dict[str, object]) -> str:
        del payload
        return "signed"

    def call_tool(self, *, tool_name: str, arguments: dict[str, object]) -> MCPToolResponse:
        self.tool_calls.append((tool_name, arguments))
        return MCPToolResponse(payload=self.responses[tool_name], request_id="req-1")

    def call_control(
        self,
        *,
        method: str,
        arguments: dict[str, object],
    ) -> MCPControlResponse:
        del method, arguments
        return MCPControlResponse(payload={}, request_id="req-control")

    def runtime_metadata(self) -> MCPRuntimeMetadata:
        return MCPRuntimeMetadata(
            process_status="READY",
            protocol_version="2026-08-07.p0",
            manifest_version="2026-08-07.p0",
            tool_registry_version="2026-08-06.p0",
            available_tool_count=20,
            last_safe_error_code=None,
            restart_count=0,
            process_instance_id="mcp-test",
        )

    def restart(self) -> MCPRuntimeMetadata:
        return self.runtime_metadata()

    def close(self) -> None:
        return None


def test_invalid_input_never_reaches_manifest_delegate(tmp_path: Path) -> None:
    transport, delegate, _ = _transport(tmp_path)

    with pytest.raises(MCPClientPortError) as captured:
        transport.call_tool(tool_name="gmail_get_thread", arguments={})

    assert captured.value.code is MCPClientPortErrorCode.TOOL_REJECTED
    assert captured.value.delivery_certainty is DeliveryCertainty.NOT_SENT
    assert delegate.tool_calls == []


def test_manifest_mutation_after_startup_rejects_before_delegate(tmp_path: Path) -> None:
    transport, delegate, manifest_path = _transport(tmp_path)
    manifest_path.write_text("{}", encoding="utf-8")

    with pytest.raises(MCPClientPortError) as captured:
        transport.call_tool(
            tool_name="gmail_get_thread",
            arguments={"thread_id": "thread-1"},
        )

    assert captured.value.code is MCPClientPortErrorCode.ARTIFACT_REJECTED
    assert captured.value.delivery_certainty is DeliveryCertainty.NOT_SENT
    assert delegate.tool_calls == []


def test_valid_public_and_internal_calls_cross_outer_guard(tmp_path: Path) -> None:
    transport, delegate, _ = _transport(tmp_path)

    public = transport.call_tool(
        tool_name="gmail_get_thread",
        arguments={"thread_id": "thread-1"},
    )
    internal = transport.call_tool(
        tool_name="gmail_get_attachment",
        arguments={"message_id": "message-1", "attachment_id": "attachment-1"},
    )

    assert public.payload["item"]["resource_id"] == "thread-1"  # type: ignore[index]
    assert internal.payload["attachment_id"] == "attachment-1"
    assert [name for name, _ in delegate.tool_calls] == [
        "gmail_get_thread",
        "gmail_get_attachment",
    ]


def test_malformed_read_output_is_may_have_been_sent(tmp_path: Path) -> None:
    transport, delegate, _ = _transport(tmp_path)
    delegate.responses["gmail_get_thread"] = {"item": {"resource_id": "thread-1"}}

    with pytest.raises(MCPClientPortError) as captured:
        transport.call_tool(
            tool_name="gmail_get_thread",
            arguments={"thread_id": "thread-1"},
        )

    assert captured.value.code is MCPClientPortErrorCode.SCHEMA_MISMATCH
    assert captured.value.delivery_certainty is DeliveryCertainty.MAY_HAVE_BEEN_SENT
    assert len(delegate.tool_calls) == 1


def test_malformed_write_output_is_sent_response_lost(tmp_path: Path) -> None:
    transport, delegate, _ = _transport(tmp_path)
    delegate.responses["tasks_create_task"] = {"item": {"resource_id": "task-1"}}

    with pytest.raises(MCPClientPortError) as captured:
        transport.call_tool(
            tool_name="tasks_create_task",
            arguments={
                "task_list_id": "list-1",
                "payload": {"title": "Task"},
                "claim_context": None,
            },
        )

    assert captured.value.code is MCPClientPortErrorCode.SCHEMA_MISMATCH
    assert captured.value.delivery_certainty is DeliveryCertainty.SENT_RESPONSE_LOST
    assert captured.value.request_id == "req-1"
    assert len(delegate.tool_calls) == 1


def _transport(
    tmp_path: Path,
) -> tuple[DispatchContractMCPClientPort, _FakeManifestGuard, Path]:
    manifest_path = tmp_path / "mcp-manifest.json"
    manifest_path.write_text(
        json.dumps(build_manifest_payload(), sort_keys=True),
        encoding="utf-8",
    )
    descriptor = build_google_workspace_connector_descriptor(
        MCPArtifactConfig(
            executable_path=str(Path("/tmp/fake-python").resolve()),
            manifest_path=str(manifest_path.resolve()),
            expected_binary_sha256="unused",
            expected_manifest_sha256=calculate_file_sha256(manifest_path),
            expected_manifest_version="2026-08-07.p0",
            expected_protocol_version="2026-08-07.p0",
            expected_tool_registry_version="2026-08-06.p0",
            startup_timeout_ms=1_000,
            request_timeout_ms=1_000,
            max_restart_count=1,
            environment="TEST",
            service_instance_id="svc-test",
        )
    )
    delegate = _FakeManifestGuard()
    transport = DispatchContractMCPClientPort(
        delegate=cast(ManifestEnforcedMCPClientPort, delegate),
        descriptor=descriptor,
    )
    return transport, delegate, manifest_path


def _snapshot_envelope(
    resource_type: str,
    resource_id: str,
    *,
    parent_id: str | None = None,
) -> dict[str, object]:
    return {
        "item": {
            "fixture_snapshot_id": f"snapshot-{resource_id}",
            "resource_type": resource_type,
            "resource_id": resource_id,
            "parent_id": parent_id,
            "related_resource_ids": [],
            "version": "v1",
            "recovery_fingerprint": None,
            "payload": {},
        }
    }
