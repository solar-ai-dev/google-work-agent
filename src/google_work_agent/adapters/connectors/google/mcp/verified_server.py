"""Capability-verified Google Workspace MCP child entrypoint.

The workspace tool module owns OAuth/provider mechanics and individual handlers. This
entrypoint owns the callable/schema surface: public Agent tools and internal
UI/attachment/recovery capabilities must be declared, schema-bound, and
validated before/after every handler invocation.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import cast

from google_work_agent.adapters.connectors.google.mcp import workspace_tools
from google_work_agent.adapters.mcp.capabilities import (
    INTERNAL_CAPABILITY_REGISTRY_VERSION,
    build_google_workspace_internal_capabilities,
)
from google_work_agent.adapters.connectors.runtime.stdio_mcp_client import PROTOCOL_VERSION
from google_work_agent.domain import build_p0_tool_registry
from google_work_agent.domain.claim_contract import CLAIM_CONTEXT_MAX_TTL_MS
from google_work_agent.domain.google_workspace_tool_contracts import (
    ToolContractViolation,
    google_workspace_tool_contract,
    validate_tool_input,
    validate_tool_output,
)
from google_work_agent.ports import DeliveryCertainty

# Production ClaimContext validation consumes the Domain TTL authority. The
# legacy module keeps provider mechanics only; its historical literal is not
# allowed to determine the active runtime boundary.
workspace_tools.CLAIM_CONTEXT_MAX_TTL_MS = CLAIM_CONTEXT_MAX_TTL_MS

type ToolHandler = Callable[
    [workspace_tools._WorkspaceState, dict[str, object]],
    dict[str, object],
]


class _VerifiedToolContractError(RuntimeError):
    def __init__(self, *, safe_code: str, certainty: DeliveryCertainty) -> None:
        super().__init__(safe_code)
        self.safe_code = safe_code
        self.certainty = certainty


def main() -> None:
    try:
        state = workspace_tools._WorkspaceState()
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
            workspace_tools._write(
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
            workspace_tools._write({"id": request_id, "payload": _dispatch(state, request)})
        except _VerifiedToolContractError as error:
            workspace_tools._write(
                {
                    "id": request_id,
                    "error": _error_payload(
                        code="TOOL_REJECTED",
                        message=error.safe_code,
                        certainty=error.certainty,
                    ),
                }
            )
        except workspace_tools._OAuthConfigurationError as error:
            workspace_tools._write(
                {
                    "id": request_id,
                    "error": _error_payload(
                        code="CONFIGURATION_ERROR",
                        message=error.safe_code,
                        certainty=DeliveryCertainty.NOT_SENT,
                    ),
                }
            )
        except workspace_tools._OAuthExchangeError:
            workspace_tools._write(
                {
                    "id": request_id,
                    "error": _error_payload(
                        code="TOOL_REJECTED",
                        message="Google OAuth token exchange failed.",
                        certainty=DeliveryCertainty.NOT_SENT,
                    ),
                }
            )
        except workspace_tools._WorkspaceToolError as error:
            workspace_tools._write(
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
            workspace_tools._write(
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
            workspace_tools._write(
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
    error: workspace_tools._WorkspaceToolError,
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
    state: workspace_tools._WorkspaceState,
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
        if method == "mcp.list_capability_contracts":
            _validate_declared_surface()
            return {"contracts": list(_declared_contract_descriptors())}
        return workspace_tools._control_call(state, method=method)
    if message_type == "tool_call":
        return _tool_call(
            state,
            tool_name=str(request["tool_name"]),
            arguments=cast(dict[str, object], request["arguments"]),
        )
    raise ValueError("unsupported message type")


def _tool_call(
    state: workspace_tools._WorkspaceState,
    *,
    tool_name: str,
    arguments: dict[str, object],
) -> dict[str, object]:
    allowed = frozenset(_declared_public_tool_names()) | frozenset(
        _declared_internal_capability_names()
    )
    if tool_name not in allowed:
        raise workspace_tools._WorkspaceToolError("TOOL_NOT_AVAILABLE")
    try:
        validate_tool_input(tool_name, arguments)
    except ToolContractViolation as error:
        raise _VerifiedToolContractError(
            safe_code="INVALID_ARGUMENT",
            certainty=DeliveryCertainty.NOT_SENT,
        ) from error

    result = _handler_for(tool_name)(state, arguments)
    try:
        validate_tool_output(tool_name, result)
    except ToolContractViolation as error:
        raise _VerifiedToolContractError(
            safe_code="INVALID_MCP_OUTPUT",
            certainty=_output_contract_failure_certainty(tool_name),
        ) from error
    return result


def _output_contract_failure_certainty(tool_name: str) -> DeliveryCertainty:
    entry = build_p0_tool_registry().get(tool_name)
    if entry is None or entry.effect_type.value == "READ":
        return DeliveryCertainty.MAY_HAVE_BEEN_SENT
    return DeliveryCertainty.SENT_RESPONSE_LOST


def _declared_public_tool_names() -> tuple[str, ...]:
    return tuple(entry.tool_name for entry in build_p0_tool_registry().list_entries())


def _declared_internal_capability_names() -> tuple[str, ...]:
    return tuple(
        sorted(
            capability.tool_name
            for capability in build_google_workspace_internal_capabilities()
        )
    )


def _declared_contract_descriptors() -> tuple[dict[str, object], ...]:
    internal = {
        capability.tool_name: capability.category.value
        for capability in build_google_workspace_internal_capabilities()
    }
    descriptors: list[dict[str, object]] = []
    for tool_name in sorted(set(_declared_public_tool_names()) | set(internal)):
        contract = google_workspace_tool_contract(tool_name)
        descriptors.append(
            {
                "tool_name": tool_name,
                "category": internal.get(tool_name, "AGENT_TOOL"),
                "input_schema_version": contract.input_schema_version,
                "output_schema_version": contract.output_schema_version,
                "tool_schema_hash": contract.schema_hash,
            }
        )
    return tuple(descriptors)


def _validate_declared_surface() -> None:
    public_names = frozenset(_declared_public_tool_names())
    internal_names = frozenset(_declared_internal_capability_names())
    if public_names & internal_names:
        raise workspace_tools._WorkspaceToolError("CAPABILITY_SURFACE_MISMATCH")
    for tool_name in public_names | internal_names:
        _handler_for(tool_name)
        google_workspace_tool_contract(tool_name)


def _handler_for(tool_name: str) -> ToolHandler:
    handler = getattr(workspace_tools, f"_{tool_name}", None)
    if not callable(handler):
        raise workspace_tools._WorkspaceToolError("CAPABILITY_SURFACE_MISMATCH")
    return cast(ToolHandler, handler)


if __name__ == "__main__":
    main()
