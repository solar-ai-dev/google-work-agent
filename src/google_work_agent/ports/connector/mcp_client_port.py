"""MCP transport port definitions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from google_work_agent.ports.google_workspace import DeliveryCertainty

type JsonValue = Any


@dataclass(frozen=True, slots=True)
class MCPToolResponse:
    """Minimal transport-level tool response."""

    payload: dict[str, JsonValue]
    request_id: str


@dataclass(frozen=True, slots=True)
class MCPControlResponse:
    """Transport-level response for non-tool control requests."""

    payload: dict[str, JsonValue]
    request_id: str


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


class MCPClientPortErrorCode(StrEnum):
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
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"


class MCPClientPortError(RuntimeError):
    """Transport-level failure with exact delivery certainty.

    ``dispatch_started`` remains as a compatibility projection. New code must
    preserve ``delivery_certainty`` end-to-end so ``SENT_RESPONSE_LOST`` is not
    collapsed into the same state as ``MAY_HAVE_BEEN_SENT``.
    """

    def __init__(
        self,
        *,
        code: MCPClientPortErrorCode,
        message: str,
        delivery_certainty: DeliveryCertainty | None = None,
        dispatch_started: bool = False,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.delivery_certainty = delivery_certainty or (
            DeliveryCertainty.MAY_HAVE_BEEN_SENT if dispatch_started else DeliveryCertainty.NOT_SENT
        )
        self.dispatch_started = self.delivery_certainty is not DeliveryCertainty.NOT_SENT
        self.request_id = request_id


class MCPClientPort(Protocol):
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
