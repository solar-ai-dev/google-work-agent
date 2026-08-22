"""Stable connector runtime lifecycle boundary.

The connector runtime handle is intentionally expressed only in terms of the
MCP transport Port.  Concrete MCP transport implementations belong to
``adapters.mcp`` and must never leak into the Core Port boundary.
"""

from __future__ import annotations

from typing import Protocol

from google_work_agent.ports.mcp_transport import (
    MCPRuntimeMetadata,
    MCPTransport,
)


class ConnectorRuntimeHandle(Protocol):
    """Lifecycle surface exposed by a connector-owned MCP runtime."""

    def start(self) -> MCPTransport: ...

    def health(self) -> MCPRuntimeMetadata: ...

    def restart(self) -> MCPRuntimeMetadata: ...

    def close(self) -> None: ...
