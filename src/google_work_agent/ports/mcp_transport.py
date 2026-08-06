"""MCP transport port definitions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

type JsonValue = Any


@dataclass(frozen=True, slots=True)
class MCPToolResponse:
    """Minimal transport-level tool response."""

    payload: dict[str, JsonValue]


class MCPTransportErrorCode(StrEnum):
    """Deterministic transport failure codes."""

    TIMEOUT = "TIMEOUT"
    PROCESS_UNAVAILABLE = "PROCESS_UNAVAILABLE"
    CONNECTION_CLOSED = "CONNECTION_CLOSED"
    MALFORMED_RESPONSE = "MALFORMED_RESPONSE"
    SCHEMA_MISMATCH = "SCHEMA_MISMATCH"


class MCPTransportError(RuntimeError):
    """Transport-level failure."""

    def __init__(self, *, code: MCPTransportErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class MCPTransport(Protocol):
    """Minimal MCP transport needed by future adapter contract tests."""

    def call_tool(self, *, tool_name: str, arguments: dict[str, JsonValue]) -> MCPToolResponse:
        """Invoke one MCP tool."""
