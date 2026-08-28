"""MCP transport port definitions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal, Protocol

from google_work_agent.ports.connector.contracts.google_workspace import DeliveryCertainty

type JsonValue = Any


@dataclass(frozen=True, slots=True)
class MCPToolDescriptorV1:
    schema_version: Literal[1]
    connector_id: str
    tool_id: str
    input_schema_ref: str
    output_schema_ref: str
    registry_entry_hash: str


@dataclass(frozen=True, slots=True)
class MCPToolCallResultV1:
    schema_version: Literal[1]
    tool_id: str
    transport_status: Literal["OK", "ERROR", "TIMEOUT", "DISCONNECTED"]
    payload: JsonValue | None
    error_code: str | None


@dataclass(frozen=True, slots=True)
class MCPRestartResultV1:
    schema_version: Literal[1]
    restarted: bool
    reason_code: str | None


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
    """Connector-id-aware MCP runtime client boundary."""

    def list_tools(self, connector_id: str) -> list[MCPToolDescriptorV1]: ...

    def call_tool(
        self,
        connector_id: str,
        tool_id: str,
        arguments: JsonValue,
        timeout_ms: int,
    ) -> MCPToolCallResultV1: ...

    def restart_once(self, connector_id: str) -> MCPRestartResultV1: ...
