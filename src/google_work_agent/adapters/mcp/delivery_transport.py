"""Delivery-certainty preserving subprocess MCP transport."""

from __future__ import annotations

import time
from queue import Empty
from typing import cast

from google_work_agent.adapters.mcp.transport import JsonObject, SubprocessMCPTransport
from google_work_agent.ports import (
    DeliveryCertainty,
    MCPTransportError,
    MCPTransportErrorCode,
)


class DeliveryAwareSubprocessMCPTransport(SubprocessMCPTransport):
    """Preserve the canonical three-state delivery signal from MCP errors.

    Older child processes that only expose ``dispatch_started`` remain
    compatible, but that boolean is only a fallback projection. New verified
    children emit ``delivery_certainty`` explicitly.
    """

    def _wait_for_response(self, *, request_id: str) -> JsonObject:
        deadline = time.monotonic() + (self._config.request_timeout_ms / 1000)
        while time.monotonic() < deadline:
            try:
                message = self._stdout_queue.get(timeout=0.05)
            except Empty as error:
                process = self._process
                if process is None or process.poll() is not None:
                    raise MCPTransportError(
                        code=MCPTransportErrorCode.CONNECTION_CLOSED,
                        message="mcp child exited before responding",
                        delivery_certainty=DeliveryCertainty.MAY_HAVE_BEEN_SENT,
                        request_id=request_id,
                    ) from error
                continue
            if str(message.get("id")) != request_id:
                raise MCPTransportError(
                    code=MCPTransportErrorCode.MALFORMED_RESPONSE,
                    message="unexpected response id",
                    delivery_certainty=DeliveryCertainty.MAY_HAVE_BEEN_SENT,
                    request_id=request_id,
                )
            if "error" in message:
                error_payload = cast(dict[str, object], message["error"])
                certainty = _delivery_certainty_from_error_payload(error_payload)
                raise MCPTransportError(
                    code=MCPTransportErrorCode(
                        str(error_payload.get("code", "MALFORMED_RESPONSE"))
                    ),
                    message=str(error_payload.get("message", "mcp request failed")),
                    delivery_certainty=certainty,
                    request_id=request_id,
                )
            return cast(JsonObject, message.get("payload", {}))
        raise MCPTransportError(
            code=MCPTransportErrorCode.TIMEOUT,
            message="mcp request timed out",
            delivery_certainty=DeliveryCertainty.MAY_HAVE_BEEN_SENT,
            request_id=request_id,
        )


def _delivery_certainty_from_error_payload(
    payload: dict[str, object],
) -> DeliveryCertainty:
    raw = payload.get("delivery_certainty")
    if raw is not None:
        try:
            return DeliveryCertainty(str(raw))
        except ValueError as error:
            raise MCPTransportError(
                code=MCPTransportErrorCode.MALFORMED_RESPONSE,
                message="invalid MCP delivery certainty",
                delivery_certainty=DeliveryCertainty.MAY_HAVE_BEEN_SENT,
            ) from error
    return (
        DeliveryCertainty.MAY_HAVE_BEEN_SENT
        if bool(payload.get("dispatch_started", True))
        else DeliveryCertainty.NOT_SENT
    )
