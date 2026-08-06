"""Queued MCP transport test double."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from google_work_agent.ports import (
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
        self._failures: list[QueuedMCPFailure] = []
        self.call_log: list[MCPCallRecord] = []

    def queue_response(self, payload: dict[str, object]) -> None:
        """Queue one successful response."""

        self._responses.append(MCPToolResponse(payload=deepcopy(payload)))

    def queue_failure(self, failure: QueuedMCPFailure) -> None:
        """Queue one transport failure."""

        self._failures.append(failure)

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
