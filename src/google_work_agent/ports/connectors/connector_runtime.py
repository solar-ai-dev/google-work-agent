"""Stable connector runtime lifecycle boundary.

The connector runtime handle is intentionally expressed only in terms of the
MCP transport Port. Concrete MCP transport implementations belong to
``adapters.mcp`` and must never leak into the Core Port boundary.
"""

from __future__ import annotations

from typing import Protocol

from google_work_agent.ports.connector.mcp_client_port import (
    MCPRuntimeMetadata,
    MCPClientPort,
)


class ConnectorRuntimeHandle(Protocol):
    """Lifecycle surface exposed by a connector-owned MCP runtime."""

    @property
    def connector_id(self) -> str: ...

    def start(self) -> MCPClientPort: ...

    def health(self) -> MCPRuntimeMetadata: ...

    def restart(self) -> MCPRuntimeMetadata: ...

    def close(self) -> None: ...
