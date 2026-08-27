"""Single process-local connector_id to active MCP runtime binding authority."""

from __future__ import annotations

from threading import RLock
from typing import Protocol

from google_work_agent.ports.connector.mcp_client_port import (
    JsonValue,
    MCPRestartResultV1,
    MCPToolCallResultV1,
    MCPToolDescriptorV1,
)


class ConnectorRuntimeHandle(Protocol):
    def list_tools(self) -> list[MCPToolDescriptorV1]: ...

    def call_tool(
        self, tool_id: str, arguments: JsonValue, timeout_ms: int
    ) -> MCPToolCallResultV1: ...

    def restart_once(self) -> MCPRestartResultV1: ...

    def close(self) -> None: ...


class ConnectorRuntimeRegistry:
    """Own exactly one active runtime handle per installed connector."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._handles: dict[str, ConnectorRuntimeHandle] = {}

    def register(self, connector_id: str, runtime_handle: ConnectorRuntimeHandle) -> None:
        if not connector_id.strip():
            raise ValueError("connector_id is required")
        with self._lock:
            if connector_id in self._handles:
                raise ValueError(f"connector runtime already registered: {connector_id}")
            self._handles[connector_id] = runtime_handle

    def resolve(self, connector_id: str) -> ConnectorRuntimeHandle:
        with self._lock:
            try:
                return self._handles[connector_id]
            except KeyError as error:
                raise LookupError(f"connector runtime not registered: {connector_id}") from error

    def connector_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._handles))

    def close_all(self) -> None:
        with self._lock:
            handles = tuple(self._handles.values())
            self._handles.clear()
        for handle in handles:
            handle.close()


__all__ = ["ConnectorRuntimeHandle", "ConnectorRuntimeRegistry"]
