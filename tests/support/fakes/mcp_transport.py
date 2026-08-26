"""Queued MCP transport test double."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from google_work_agent.ports import (
    MCPControlResponse,
    MCPRuntimeMetadata,
    MCPToolResponse,
    MCPClientPortError,
    MCPClientPortErrorCode,
)


@dataclass(frozen=True, slots=True)
class MCPCallRecord:
    """Recorded MCP tool invocation."""

    tool_name: str
    arguments: dict[str, object]


@dataclass(frozen=True, slots=True)
class QueuedMCPFailure:
    """One queued MCP transport failure."""

    code: MCPClientPortErrorCode
    message: str
    dispatch_started: bool = False


class FakeMCPClientPort:
    """Queue-driven MCP transport fake with no subprocess usage."""

    def __init__(self) -> None:
        self._responses: list[dict[str, object]] = []
        self._control_responses: list[dict[str, object]] = []
        self._failures: list[QueuedMCPFailure] = []
        self.call_log: list[MCPCallRecord] = []
        self._request_counter = 0

    def _next_request_id(self) -> str:
        # Mirrors StdioMCPClientAdapter: a fresh id per call, never reused
        # across retries, so tests can assert on real correlation behavior.
        self._request_counter += 1
        return f"req-{self._request_counter}"

    def queue_response(self, payload: dict[str, object]) -> None:
        """Queue one successful response."""

        self._responses.append(deepcopy(payload))

    def queue_failure(self, failure: QueuedMCPFailure) -> None:
        """Queue one transport failure."""

        self._failures.append(failure)

    def queue_control_response(self, payload: dict[str, object]) -> None:
        self._control_responses.append(deepcopy(payload))

    def call_tool(self, *, tool_name: str, arguments: dict[str, object]) -> MCPToolResponse:
        """Return the next queued response or failure."""

        self.call_log.append(MCPCallRecord(tool_name=tool_name, arguments=deepcopy(arguments)))
        request_id = self._next_request_id()
        if self._failures:
            failure = self._failures.pop(0)
            raise MCPClientPortError(
                code=failure.code,
                message=failure.message,
                dispatch_started=failure.dispatch_started,
                request_id=request_id,
            )
        if not self._responses:
            raise RuntimeError("no queued MCP response available")
        payload = self._responses.pop(0)
        return MCPToolResponse(payload=deepcopy(payload), request_id=request_id)

    def call_control(self, *, method: str, arguments: dict[str, object]) -> MCPControlResponse:
        self.call_log.append(MCPCallRecord(tool_name=method, arguments=deepcopy(arguments)))
        request_id = self._next_request_id()
        if self._failures:
            failure = self._failures.pop(0)
            raise MCPClientPortError(
                code=failure.code,
                message=failure.message,
                dispatch_started=failure.dispatch_started,
                request_id=request_id,
            )
        if not self._control_responses:
            raise RuntimeError("no queued MCP control response available")
        payload = self._control_responses.pop(0)
        return MCPControlResponse(payload=deepcopy(payload), request_id=request_id)

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
