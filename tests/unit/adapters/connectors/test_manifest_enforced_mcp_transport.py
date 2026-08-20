from __future__ import annotations

import json
from pathlib import Path

import pytest

from google_work_agent.adapters.connectors import build_google_workspace_connector_descriptor
from google_work_agent.adapters.mcp import (
    MCPArtifactConfig,
    build_manifest_payload,
    calculate_file_sha256,
)
from google_work_agent.adapters.mcp.capabilities import (
    INTERNAL_CAPABILITY_REGISTRY_VERSION,
    build_google_workspace_internal_capabilities,
)
from google_work_agent.adapters.mcp.manifest_guard import ManifestEnforcedMCPTransport
from google_work_agent.adapters.mcp.transport import MCPConnectorDescriptor
from google_work_agent.ports import (
    MCPControlResponse,
    MCPRuntimeMetadata,
    MCPToolResponse,
    MCPTransportError,
    MCPTransportErrorCode,
)


class _FakeVerifiedDelegate:
    def __init__(
        self,
        *,
        internal_names: tuple[str, ...],
        internal_registry_version: str = INTERNAL_CAPABILITY_REGISTRY_VERSION,
    ) -> None:
        self.internal_names = internal_names
        self.internal_registry_version = internal_registry_version
        self.tool_calls: list[str] = []
        self.control_calls: list[str] = []
        self.closed = False

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
        del arguments
        self.tool_calls.append(tool_name)
        return MCPToolResponse(payload={}, request_id="req-tool")

    def call_control(
        self,
        *,
        method: str,
        arguments: dict[str, object],
    ) -> MCPControlResponse:
        del arguments
        self.control_calls.append(method)
        if method == "mcp.list_internal_capabilities":
            return MCPControlResponse(
                payload={
                    "internal_capability_registry_version": self.internal_registry_version,
                    "internal_capability_names": list(self.internal_names),
                },
                request_id="req-control",
            )
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
            process_instance_id=self.process_instance_id,
        )

    def restart(self) -> MCPRuntimeMetadata:
        return self.runtime_metadata()

    def close(self) -> None:
        self.closed = True


def test_unknown_tool_is_rejected_before_delegate_dispatch(tmp_path: Path) -> None:
    guard, delegate = _guard(tmp_path)

    with pytest.raises(MCPTransportError) as captured:
        guard.call_tool(tool_name="hidden_unregistered_tool", arguments={})

    assert captured.value.code is MCPTransportErrorCode.TOOL_REJECTED
    assert captured.value.dispatch_started is False
    assert delegate.tool_calls == []


def test_declared_internal_capability_is_dispatchable(tmp_path: Path) -> None:
    guard, delegate = _guard(tmp_path)

    guard.call_tool(
        tool_name="gmail_get_attachment",
        arguments={"message_id": "m1", "attachment_id": "a1"},
    )

    assert delegate.tool_calls == ["gmail_get_attachment"]


def test_declared_agent_tool_is_dispatchable(tmp_path: Path) -> None:
    guard, delegate = _guard(tmp_path)

    guard.call_tool(tool_name="gmail_get_thread", arguments={"thread_id": "t1"})

    assert delegate.tool_calls == ["gmail_get_thread"]


def test_remote_internal_surface_mismatch_fails_closed(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path)
    descriptor = _descriptor(manifest_path)
    delegate = _FakeVerifiedDelegate(internal_names=("gmail_get_attachment",))

    with pytest.raises(MCPTransportError) as captured:
        ManifestEnforcedMCPTransport(
            delegate=delegate,
            descriptor=descriptor,
            expected_internal_capabilities=build_google_workspace_internal_capabilities(),
        )

    assert captured.value.code is MCPTransportErrorCode.TOOL_REJECTED
    assert delegate.tool_calls == []


def test_remote_internal_registry_version_mismatch_fails_closed(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path)
    descriptor = _descriptor(manifest_path)
    delegate = _FakeVerifiedDelegate(
        internal_names=_expected_internal_names(),
        internal_registry_version="stale-version",
    )

    with pytest.raises(MCPTransportError) as captured:
        ManifestEnforcedMCPTransport(
            delegate=delegate,
            descriptor=descriptor,
            expected_internal_capabilities=build_google_workspace_internal_capabilities(),
        )

    assert captured.value.code is MCPTransportErrorCode.TOOL_REJECTED
    assert delegate.tool_calls == []


def test_stale_internal_manifest_contract_fails_closed(tmp_path: Path) -> None:
    payload = build_manifest_payload()
    raw_internal = payload["internal_capabilities"]
    assert isinstance(raw_internal, list)
    first = raw_internal[0]
    assert isinstance(first, dict)
    first["registry_version"] = "stale-version"
    manifest_path = tmp_path / "mcp-manifest.json"
    manifest_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    descriptor = _descriptor(manifest_path)
    delegate = _FakeVerifiedDelegate(internal_names=_expected_internal_names())

    with pytest.raises(MCPTransportError) as captured:
        ManifestEnforcedMCPTransport(
            delegate=delegate,
            descriptor=descriptor,
            expected_internal_capabilities=build_google_workspace_internal_capabilities(),
        )

    assert captured.value.code is MCPTransportErrorCode.TOOL_REJECTED
    assert delegate.tool_calls == []


def test_manifest_bytes_changed_after_descriptor_hash_are_rejected(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path)
    descriptor = _descriptor(manifest_path)
    manifest_path.write_text("{}", encoding="utf-8")
    delegate = _FakeVerifiedDelegate(internal_names=_expected_internal_names())

    with pytest.raises(MCPTransportError) as captured:
        ManifestEnforcedMCPTransport(
            delegate=delegate,
            descriptor=descriptor,
            expected_internal_capabilities=build_google_workspace_internal_capabilities(),
        )

    assert captured.value.code is MCPTransportErrorCode.ARTIFACT_REJECTED
    assert delegate.control_calls == []
    assert delegate.tool_calls == []


def _guard(tmp_path: Path) -> tuple[ManifestEnforcedMCPTransport, _FakeVerifiedDelegate]:
    manifest_path = _write_manifest(tmp_path)
    delegate = _FakeVerifiedDelegate(internal_names=_expected_internal_names())
    return (
        ManifestEnforcedMCPTransport(
            delegate=delegate,
            descriptor=_descriptor(manifest_path),
            expected_internal_capabilities=build_google_workspace_internal_capabilities(),
        ),
        delegate,
    )


def _expected_internal_names() -> tuple[str, ...]:
    return tuple(
        sorted(
            capability.tool_name
            for capability in build_google_workspace_internal_capabilities()
        )
    )


def _write_manifest(tmp_path: Path) -> Path:
    manifest_path = tmp_path / "mcp-manifest.json"
    manifest_path.write_text(
        json.dumps(build_manifest_payload(), sort_keys=True),
        encoding="utf-8",
    )
    return manifest_path


def _descriptor(manifest_path: Path) -> MCPConnectorDescriptor:
    executable = Path("/tmp/fake-python").resolve()
    return build_google_workspace_connector_descriptor(
        MCPArtifactConfig(
            executable_path=str(executable),
            manifest_path=str(manifest_path.resolve()),
            expected_binary_sha256="unused-by-guard",
            expected_manifest_sha256=calculate_file_sha256(manifest_path),
            expected_manifest_version="2026-08-07.p0",
            expected_protocol_version="2026-08-07.p0",
            expected_tool_registry_version="2026-08-06.p0",
            startup_timeout_ms=1_000,
            request_timeout_ms=1_000,
            max_restart_count=1,
            environment="DEVELOPMENT",
            service_instance_id="svc-test",
        )
    )
