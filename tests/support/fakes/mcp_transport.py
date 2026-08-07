"""Queued MCP transport test double."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from google_work_agent.ports import (
    MCPControlResponse,
    MCPRuntimeMetadata,
    MCPToolResponse,
    MCPTransportError,
    MCPTransportErrorCode,
)


@dataclass(frozen=True, slots=True)
class MCPCallRecord:
    """Recorded MCP tool invocation."""

    tool_name: str
    arguments: dict[str, object]


@dataclass(frozen=True, slots=True)
class QueuedMCPFailure:
    """One queued MCP transport failure."""

    code: MCPTransportErrorCode
    message: str


class FakeMCPTransport:
    """Queue-driven MCP transport fake with no subprocess usage."""

    def __init__(self) -> None:
        self._responses: list[MCPToolResponse] = []
        self._control_responses: list[MCPControlResponse] = []
        self._failures: list[QueuedMCPFailure] = []
        self.call_log: list[MCPCallRecord] = []

    def queue_response(self, payload: dict[str, object]) -> None:
        """Queue one successful response."""

        self._responses.append(MCPToolResponse(payload=deepcopy(payload)))

    def queue_failure(self, failure: QueuedMCPFailure) -> None:
        """Queue one transport failure."""

        self._failures.append(failure)

    def queue_control_response(self, payload: dict[str, object]) -> None:
        self._control_responses.append(MCPControlResponse(payload=deepcopy(payload)))

    def call_tool(self, *, tool_name: str, arguments: dict[str, object]) -> MCPToolResponse:
        """Return the next queued response or failure."""

        self.call_log.append(MCPCallRecord(tool_name=tool_name, arguments=deepcopy(arguments)))
        if self._failures:
            failure = self._failures.pop(0)
            raise MCPTransportError(code=failure.code, message=failure.message)
        if not self._responses:
            raise RuntimeError("no queued MCP response available")
        response = self._responses.pop(0)
        return MCPToolResponse(payload=deepcopy(response.payload))

    def call_control(self, *, method: str, arguments: dict[str, object]) -> MCPControlResponse:
        self.call_log.append(MCPCallRecord(tool_name=method, arguments=deepcopy(arguments)))
        if self._failures:
            failure = self._failures.pop(0)
            raise MCPTransportError(code=failure.code, message=failure.message)
        if not self._control_responses:
            raise RuntimeError("no queued MCP control response available")
        response = self._control_responses.pop(0)
        return MCPControlResponse(payload=deepcopy(response.payload))

    def runtime_metadata(self) -> MCPRuntimeMetadata:
        return MCPRuntimeMetadata(
            process_status="READY",
            protocol_version="test",
            manifest_version="test",
            tool_registry_version="test",
            available_tool_count=0,
            last_safe_error_code=None,
            restart_count=0,
            process_instance_id="fake-process",
        )

    def close(self) -> None:
        return None
