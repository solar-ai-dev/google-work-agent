"""Connector lifecycle contracts used by the application core."""

from __future__ import annotations

from typing import Protocol

from google_work_agent.ports.mcp_transport import MCPRuntimeMetadata, MCPTransport


class ConnectorRuntimeHandle(Protocol):
    @property
    def connector_id(self) -> str: ...

    def start(self) -> MCPTransport: ...

    def health(self) -> MCPRuntimeMetadata: ...

    def restart(self) -> MCPRuntimeMetadata: ...

    def close(self) -> None: ...
