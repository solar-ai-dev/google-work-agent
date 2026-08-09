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


@dataclass(frozen=True, slots=True)
class MCPControlResponse:
    """Transport-level response for non-tool control requests."""

    payload: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class MCPRuntimeMetadata:
    """Sanitized runtime state for one MCP child process."""

    process_status: str
    protocol_version: str
    manifest_version: str
    tool_registry_version: str
    available_tool_count: int
    last_safe_error_code: str | None
    restart_count: int
    process_instance_id: str | None = None


class MCPTransportErrorCode(StrEnum):
    """Deterministic transport failure codes."""

    TIMEOUT = "TIMEOUT"
    PROCESS_UNAVAILABLE = "PROCESS_UNAVAILABLE"
    CONNECTION_CLOSED = "CONNECTION_CLOSED"
    NOT_FOUND = "NOT_FOUND"
    MALFORMED_RESPONSE = "MALFORMED_RESPONSE"
    SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
    TOOL_REJECTED = "TOOL_REJECTED"
    HANDSHAKE_FAILED = "HANDSHAKE_FAILED"
    ARTIFACT_REJECTED = "ARTIFACT_REJECTED"


class MCPTransportError(RuntimeError):
    """Transport-level failure."""

    def __init__(
        self,
        *,
        code: MCPTransportErrorCode,
        message: str,
        dispatch_started: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.dispatch_started = dispatch_started


class MCPTransport(Protocol):
    """Minimal MCP transport needed by future adapter contract tests."""

    def call_tool(self, *, tool_name: str, arguments: dict[str, JsonValue]) -> MCPToolResponse:
        """Invoke one MCP tool."""

    def call_control(
        self,
        *,
        method: str,
        arguments: dict[str, JsonValue],
    ) -> MCPControlResponse:
        """Invoke one non-tool MCP control method."""

    def runtime_metadata(self) -> MCPRuntimeMetadata:
        """Return sanitized transport runtime metadata."""

    def close(self) -> None:
        """Close the transport and any child process resources."""
