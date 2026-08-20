"""Capability-verified Google Workspace MCP child entrypoint.

The legacy server continues to own OAuth/provider mechanics and individual tool
handlers. This entrypoint owns only the callable surface: Agent tools come from
the signed Tool Registry, non-Agent UI/attachment/recovery tools come from the
explicit internal capability registry, and no other handler is dispatchable.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import cast

from google_work_agent.adapters.mcp.capabilities import (
    INTERNAL_CAPABILITY_REGISTRY_VERSION,
    build_google_workspace_internal_capabilities,
)
from google_work_agent.adapters.mcp.transport import PROTOCOL_VERSION
from google_work_agent.domain import build_p0_tool_registry
from google_work_agent.mcp import server as legacy_server
from google_work_agent.ports import DeliveryCertainty

type ToolHandler = Callable[
    [legacy_server._WorkspaceState, dict[str, object]],
    dict[str, object],
]


def main() -> None:
    try:
        state = legacy_server._WorkspaceState()
    except RuntimeError:
        state = None
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        request = cast(dict[str, object], json.loads(line))
        request_id = str(request.get("id", ""))
        if str(request.get("type")) == "shutdown":
            break
        if state is None:
            legacy_server._write(
                {
                    "id": request_id,
                    "error": _error_payload(
                        code="CONFIGURATION_ERROR",
                        message="OS keyring is unavailable.",
                        certainty=DeliveryCertainty.NOT_SENT,
                    ),
                }
            )
            continue
        try:
            legacy_server._write({"id": request_id, "payload": _dispatch(state, request)})
        except legacy_server._OAuthConfigurationError as error:
            legacy_server._write(
                {
                    "id": request_id,
                    "error": _error_payload(
                        code="CONFIGURATION_ERROR",
                        message=error.safe_code,
                        certainty=DeliveryCertainty.NOT_SENT,
                    ),
                }
            )
        except legacy_server._OAuthExchangeError:
            legacy_server._write(
                {
                    "id": request_id,
                    "error": _error_payload(
                        code="TOOL_REJECTED",
                        message="Google OAuth token exchange failed.",
                        certainty=DeliveryCertainty.NOT_SENT,
                    ),
                }
            )
        except legacy_server._WorkspaceToolError as error:
            legacy_server._write(
                {
                    "id": request_id,
                    "error": _error_payload(
                        code="TOOL_REJECTED",
                        message=error.safe_code,
                        certainty=_legacy_error_delivery_certainty(error),
                    ),
                }
            )
        except KeyError as error:
            legacy_server._write(
                {
                    "id": request_id,
                    "error": _error_payload(
                        code="NOT_FOUND",
                        message=str(error),
                        certainty=DeliveryCertainty.MAY_HAVE_BEEN_SENT,
                    ),
                }
            )
        except Exception:
            legacy_server._write(
                {
                    "id": request_id,
                    "error": _error_payload(
                        code="MALFORMED_RESPONSE",
                        message="MCP request failed.",
                        certainty=DeliveryCertainty.MAY_HAVE_BEEN_SENT,
                    ),
                }
            )


def _error_payload(
    *,
    code: str,
    message: str,
    certainty: DeliveryCertainty,
) -> dict[str, object]:
    return {
        "code": code,
        "message": message,
        "delivery_certainty": certainty.value,
        "dispatch_started": certainty is not DeliveryCertainty.NOT_SENT,
    }


def _legacy_error_delivery_certainty(
    error: legacy_server._WorkspaceToolError,
) -> DeliveryCertainty:
    explicit = getattr(error, "delivery_certainty", None)
    if isinstance(explicit, DeliveryCertainty):
        return explicit
    if isinstance(explicit, str):
        try:
            return DeliveryCertainty(explicit)
        except ValueError:
            pass
    return (
        DeliveryCertainty.MAY_HAVE_BEEN_SENT
        if error.dispatch_started
        else DeliveryCertainty.NOT_SENT
    )


def _dispatch(
    state: legacy_server._WorkspaceState,
    request: dict[str, object],
) -> dict[str, object]:
    message_type = str(request["type"])
    if message_type == "handshake":
        session_key = str(request["session_key"])
        if len(bytes.fromhex(session_key)) < 32:
            raise ValueError("session key must be at least 256 bits")
        state.service_instance_id = str(request["service_instance_id"])
        state.session_key = session_key
        return {"process_instance_id": state.process_instance_id}
    if message_type == "initialize":
        return {
            "protocol_version": PROTOCOL_VERSION,
            "manifest_version": str(request["manifest_version"]),
            "tool_registry_version": str(request["tool_registry_version"]),
            "internal_capability_registry_version": INTERNAL_CAPABILITY_REGISTRY_VERSION,
        }
    if message_type == "list_tools":
        _validate_declared_surface()
        return {"tool_names": list(_declared_public_tool_names())}
    if message_type == "control_call":
        method = str(request["method"])
        if method == "mcp.list_internal_capabilities":
            _validate_declared_surface()
            return {
                "internal_capability_registry_version": (
                    INTERNAL_CAPABILITY_REGISTRY_VERSION
                ),
                "internal_capability_names": list(_declared_internal_capability_names()),
            }
        return legacy_server._control_call(state, method=method)
    if message_type == "tool_call":
        return _tool_call(
            state,
            tool_name=str(request["tool_name"]),
            arguments=cast(dict[str, object], request["arguments"]),
        )
    raise ValueError("unsupported message type")


def _tool_call(
    state: legacy_server._WorkspaceState,
    *,
    tool_name: str,
    arguments: dict[str, object],
) -> dict[str, object]:
    allowed = frozenset(_declared_public_tool_names()) | frozenset(
        _declared_internal_capability_names()
    )
    if tool_name not in allowed:
        raise legacy_server._WorkspaceToolError("TOOL_NOT_AVAILABLE")
    handler = _handler_for(tool_name)
    return handler(state, arguments)


def _declared_public_tool_names() -> tuple[str, ...]:
    return tuple(entry.tool_name for entry in build_p0_tool_registry().list_entries())


def _declared_internal_capability_names() -> tuple[str, ...]:
    return tuple(
        sorted(
            capability.tool_name
            for capability in build_google_workspace_internal_capabilities()
        )
    )


def _validate_declared_surface() -> None:
    public_names = frozenset(_declared_public_tool_names())
    internal_names = frozenset(_declared_internal_capability_names())
    if public_names & internal_names:
        raise legacy_server._WorkspaceToolError("CAPABILITY_SURFACE_MISMATCH")
    for tool_name in public_names | internal_names:
        _handler_for(tool_name)


def _handler_for(tool_name: str) -> ToolHandler:
    handler = getattr(legacy_server, f"_{tool_name}", None)
    if not callable(handler):
        raise legacy_server._WorkspaceToolError("CAPABILITY_SURFACE_MISMATCH")
    return cast(ToolHandler, handler)


if __name__ == "__main__":
    main()
