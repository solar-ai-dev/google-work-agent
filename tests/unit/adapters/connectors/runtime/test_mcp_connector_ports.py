from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from google_work_agent.adapters.connectors.runtime.connector_runtime_registry import (
    ConnectorRuntimeRegistry,
)
from google_work_agent.adapters.connectors.runtime.mcp_connector_read import McpConnectorReadAdapter
from google_work_agent.adapters.connectors.runtime.mcp_connector_write import (
    McpConnectorWriteAdapter,
)
from google_work_agent.application.tool_registry import load_signed_tool_registry
from google_work_agent.ports.connector.mcp_client_port import (
    MCPRestartResultV1,
    MCPRuntimeMetadata,
    MCPToolCallResultV1,
    MCPToolDescriptorV1,
)


@dataclass
class _Client:
    response: MCPToolCallResultV1
    process_instance_id: str = "process-1"
    calls: list[tuple[str, str, Any, int]] = field(default_factory=list)

    def list_tools(self, connector_id: str) -> list[MCPToolDescriptorV1]:
        return load_signed_tool_registry().descriptor_expectations(connector_id)

    def call_tool(
        self, connector_id: str, tool_id: str, arguments: Any, timeout_ms: int
    ) -> MCPToolCallResultV1:
        self.calls.append((connector_id, tool_id, arguments, timeout_ms))
        return self.response

    def restart_once(self, connector_id: str) -> MCPRestartResultV1:
        return MCPRestartResultV1(1, True, connector_id)

    def sign_claim_context(self, payload: dict[str, object]) -> str:
        assert payload["mcp_process_instance_id"] == self.process_instance_id
        return "signature-1"

    def close(self) -> None:
        pass


@dataclass
class _Runtime:
    client: _Client

    def runtime_metadata(self) -> MCPRuntimeMetadata:
        return MCPRuntimeMetadata("READY", "1", "1", "1", 1, None, 0, "process-1")

    def list_tools(self) -> list[MCPToolDescriptorV1]:
        return self.client.list_tools("google_workspace")

    def call_tool(self, tool_id: str, arguments: Any, timeout_ms: int) -> MCPToolCallResultV1:
        return self.client.call_tool("google_workspace", tool_id, arguments, timeout_ms)

    def restart_once(self) -> MCPRestartResultV1:
        return self.client.restart_once("google_workspace")

    def close(self) -> None:
        self.client.close()


def _registry(client: _Client) -> ConnectorRuntimeRegistry:
    registry = ConnectorRuntimeRegistry()
    registry.register("google_workspace", _Runtime(client))
    return registry


def test_read_adapter_requires_signed_binding_and_projects_bounded_output() -> None:
    client = _Client(MCPToolCallResultV1(1, "gmail_get_thread", "OK", {"request_id": "r1"}, None))
    binding = load_signed_tool_registry().bind_required(
        "google_workspace", "gmail_get_thread", "READ"
    )

    result = McpConnectorReadAdapter(
        runtime_registry=_registry(client), mcp_client=client
    ).execute_read(binding, {"thread_id": "thread-1"})

    assert result.request_id == "r1"
    assert client.calls[0][1] == "gmail_get_thread"


def test_write_adapter_injects_process_bound_signed_claim() -> None:
    client = _Client(MCPToolCallResultV1(1, "gmail_send", "OK", {"request_id": "r1"}, None))
    binding = load_signed_tool_registry().bind_required("google_workspace", "gmail_send", "SEND")

    result = McpConnectorWriteAdapter(
        runtime_registry=_registry(client), mcp_client=client
    ).execute_write(binding, {"draft_id": "draft-1"}, {"claim_id": "claim-1"})

    sent = client.calls[0][2]
    assert isinstance(sent, dict)
    assert sent["claim_context"]["signature"] == "signature-1"
    assert result.success is True


def test_read_and_write_adapters_reject_cross_effect_binding() -> None:
    client = _Client(MCPToolCallResultV1(1, "unused", "OK", {}, None))
    registry = _registry(client)
    signed = load_signed_tool_registry()

    with pytest.raises(ValueError, match="READ binding"):
        McpConnectorReadAdapter(runtime_registry=registry, mcp_client=client).execute_read(
            signed.bind_required("google_workspace", "gmail_send", "SEND"), {}
        )
    with pytest.raises(ValueError, match="WRITE binding"):
        McpConnectorWriteAdapter(runtime_registry=registry, mcp_client=client).execute_write(
            signed.bind_required("google_workspace", "gmail_get_thread", "READ"), {}, {}
        )
