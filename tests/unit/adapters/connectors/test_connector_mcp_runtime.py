from typing import Any

from google_work_agent.adapters.connectors.connector_mcp_runtime import ConnectorMcpRuntime
from google_work_agent.adapters.mcp import MCPArtifactConfig, MCPConnectorDescriptor
from google_work_agent.ports import MCPControlResponse, MCPRuntimeMetadata, MCPToolResponse
from google_work_agent.ports.connector.migration_contracts.google_workspace_tool_registry import (
    build_google_workspace_tool_registry,
)


class _Transport:
    def __init__(self) -> None:
        self.restart_count = 0
        self.closed = False

    def call_tool(self, *, tool_name: str, arguments: dict[str, Any]) -> MCPToolResponse:
        return MCPToolResponse(payload={}, request_id="req-fake-1")

    def call_control(self, *, method: str, arguments: dict[str, Any]) -> MCPControlResponse:
        return MCPControlResponse(payload={}, request_id="req-fake-1")

    def runtime_metadata(self) -> MCPRuntimeMetadata:
        return _metadata(restart_count=self.restart_count)

    def restart(self) -> MCPRuntimeMetadata:
        self.restart_count += 1
        return self.runtime_metadata()

    def close(self) -> None:
        self.closed = True


def test_connector_mcp_runtime_owns_start_health_restart_and_close() -> None:
    transport = _Transport()
    runtime = ConnectorMcpRuntime(
        descriptor=_descriptor(),
        transport_factory=lambda _descriptor: transport,
    )

    assert runtime.connector_id == "google_workspace"
    assert runtime.start() is transport
    assert runtime.start() is transport
    assert runtime.health().process_status == "READY"
    assert runtime.restart().restart_count == 1

    runtime.close()

    assert transport.closed
    assert runtime.health().process_status == "READY"


def _descriptor() -> MCPConnectorDescriptor:
    return MCPConnectorDescriptor(
        connector_id="google_workspace",
        artifact_config=MCPArtifactConfig(
            executable_path="unused",
            manifest_path="unused",
            expected_binary_sha256="unused",
            expected_manifest_sha256="unused",
            expected_manifest_version="v1",
            expected_protocol_version="v1",
            expected_tool_registry_version="v1",
            startup_timeout_ms=1,
            request_timeout_ms=1,
            max_restart_count=1,
            environment="TEST",
            service_instance_id="svc-test",
        ),
        expected_tool_registry=build_google_workspace_tool_registry(),
    )


def _metadata(*, restart_count: int) -> MCPRuntimeMetadata:
    return MCPRuntimeMetadata(
        process_status="READY",
        protocol_version="v1",
        manifest_version="v1",
        tool_registry_version="v1",
        available_tool_count=20,
        last_safe_error_code=None,
        restart_count=restart_count,
        process_instance_id="mcp-1",
    )
