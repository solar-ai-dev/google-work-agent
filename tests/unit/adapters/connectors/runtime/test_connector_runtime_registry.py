from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from google_work_agent.adapters.connectors.runtime.connector_runtime_registry import (
    ConnectorRuntimeRegistry,
)
from google_work_agent.ports.connector.mcp_client_port import (
    MCPRestartResultV1,
    MCPRuntimeMetadata,
    MCPToolCallResultV1,
    MCPToolDescriptorV1,
)


@dataclass
class _Runtime:
    closed: bool = False

    def runtime_metadata(self) -> MCPRuntimeMetadata:
        return MCPRuntimeMetadata("READY", "1", "1", "1", 0, None, 0)

    def list_tools(self) -> list[MCPToolDescriptorV1]:
        return []

    def call_tool(self, tool_id: str, arguments: Any, timeout_ms: int) -> MCPToolCallResultV1:
        del tool_id, arguments, timeout_ms
        raise AssertionError("tool call is outside this registry test")

    def restart_once(self) -> MCPRestartResultV1:
        return MCPRestartResultV1(1, False, None)

    def close(self) -> None:
        self.closed = True


def test_registry_rejects_duplicate_authority_and_closes_each_runtime() -> None:
    registry = ConnectorRuntimeRegistry()
    runtime = _Runtime()
    registry.register("google_workspace", runtime)

    assert registry.resolve("google_workspace") is runtime
    assert registry.connector_ids() == ("google_workspace",)
    with pytest.raises(ValueError, match="already registered"):
        registry.register("google_workspace", _Runtime())

    registry.close_all()

    assert runtime.closed is True
    assert registry.connector_ids() == ()
