"""Connector-owned MCP transport lifecycle."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from google_work_agent.adapters.connectors.runtime.stdio_mcp_client import MCPConnectorDescriptor
from google_work_agent.ports import MCPRuntimeMetadata, MCPClientPort


class RestartableMCPClientPort(MCPClientPort, Protocol):
    def restart(self) -> MCPRuntimeMetadata: ...


class ConnectorMcpRuntime:
    """Own one connector's MCP transport lifecycle without provider fallback."""

    def __init__(
        self,
        *,
        descriptor: MCPConnectorDescriptor,
        transport_factory: Callable[[MCPConnectorDescriptor], RestartableMCPClientPort],
    ) -> None:
        self._descriptor = descriptor
        self._transport_factory = transport_factory
        self._transport: RestartableMCPClientPort | None = None
        self._last_transport: RestartableMCPClientPort | None = None

    @property
    def connector_id(self) -> str:
        return self._descriptor.connector_id

    @property
    def descriptor(self) -> MCPConnectorDescriptor:
        return self._descriptor

    @property
    def transport(self) -> RestartableMCPClientPort:
        if self._transport is None:
            raise RuntimeError(f"connector runtime is not started: {self.connector_id}")
        return self._transport

    @property
    def transport_for_diagnostics(self) -> RestartableMCPClientPort:
        transport = self._transport or self._last_transport
        if transport is None:
            raise RuntimeError(f"connector runtime has not started: {self.connector_id}")
        return transport

    def start(self) -> MCPClientPort:
        if self._transport is None:
            self._transport = self._transport_factory(self._descriptor)
        return self._transport

    def health(self) -> MCPRuntimeMetadata:
        return self.transport_for_diagnostics.runtime_metadata()

    def restart(self) -> MCPRuntimeMetadata:
        return self.transport.restart()

    def close(self) -> None:
        if self._transport is None:
            return
        self._transport.close()
        self._last_transport = self._transport
        self._transport = None
