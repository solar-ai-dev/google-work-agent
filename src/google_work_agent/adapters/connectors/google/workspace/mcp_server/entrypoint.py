"""Capability-verified Google Workspace MCP child entrypoint."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import cast

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    credential_provider as workspace_tools,
)
from google_work_agent.adapters.connectors.google.workspace.mcp_server.composition import (
    compose_server_state,
)
from google_work_agent.adapters.connectors.google.workspace.mcp_server.dispatch_tool import (
    dispatch_internal_tool,
    dispatch_tool,
    has_internal_operation,
    has_operation,
)
from google_work_agent.adapters.connectors.google.workspace.mcp_server.project_registry import (
    INTERNAL_CAPABILITY_REGISTRY_VERSION,
    ToolContractViolation,
    build_google_workspace_internal_capabilities,
    get_projected_tool,
    google_workspace_tool_contract,
    project_registry,
    registry_manifest_hash,
    validate_tool_input,
    validate_tool_output,
)
from google_work_agent.adapters.connectors.runtime.stdio_mcp_client import PROTOCOL_VERSION
from google_work_agent.ports.connector.contracts.google_workspace import DeliveryCertainty


class _VerifiedToolContractError(RuntimeError):
    def __init__(self, *, safe_code: str, certainty: DeliveryCertainty) -> None:
        super().__init__(safe_code)
        self.safe_code = safe_code
        self.certainty = certainty


def run_server(
    state_factory: Callable[[], workspace_tools.GoogleWorkspaceCredentialProvider] = (
        compose_server_state
    ),
) -> None:
    try:
        state = state_factory()
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
                        code=_workspace_error_code(error.safe_code),
                        message=error.safe_code,
                        certainty=error.delivery_certainty,
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
    }


def _workspace_error_code(safe_code: str) -> str:
    if safe_code in {"REAUTH_REQUIRED", "OAUTH_NOT_CONNECTED"}:
        return "AUTH_REQUIRED"
    if safe_code == "PERMISSION_DENIED":
        return "PERMISSION_DENIED"
    return "TOOL_REJECTED"


def _dispatch(
    state: workspace_tools.GoogleWorkspaceCredentialProvider,
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
        expected_hash = registry_manifest_hash()
        if str(request["registry_manifest_hash"]) != expected_hash:
            raise workspace_tools._WorkspaceToolError("REGISTRY_PROJECTION_MISMATCH")
        return {
            "protocol_version": PROTOCOL_VERSION,
            "manifest_version": str(request["manifest_version"]),
            "registry_manifest_hash": expected_hash,
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
                "internal_capability_registry_version": (INTERNAL_CAPABILITY_REGISTRY_VERSION),
                "internal_capability_names": list(_declared_internal_capability_names()),
            }
        if method == "mcp.list_capability_contracts":
            _validate_declared_surface()
            return {"contracts": list(_declared_contract_descriptors())}
        return workspace_tools._control_call(
            state,
            method=method,
            arguments=cast(dict[str, object], request.get("arguments", {})),
        )
    if message_type == "tool_call":
        return _tool_call(
            state,
            tool_name=str(request["tool_name"]),
            arguments=cast(dict[str, object], request["arguments"]),
        )
    raise ValueError("unsupported message type")


def _tool_call(
    state: workspace_tools.GoogleWorkspaceCredentialProvider,
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

    if tool_name in frozenset(_declared_public_tool_names()):
        result = dispatch_tool(state, tool_name, arguments)
    else:
        result = dispatch_internal_tool(state, tool_name, arguments)
    try:
        validate_tool_output(tool_name, result)
    except ToolContractViolation as error:
        raise _VerifiedToolContractError(
            safe_code="INVALID_MCP_OUTPUT",
            certainty=_output_contract_failure_certainty(tool_name),
        ) from error
    return result


def _output_contract_failure_certainty(tool_name: str) -> DeliveryCertainty:
    entry = get_projected_tool(tool_name)
    contract = google_workspace_tool_contract(tool_name)
    properties = cast(dict[str, object], contract.input_schema.get("properties", {}))
    if entry is None or "claim_context" not in properties:
        return DeliveryCertainty.MAY_HAVE_BEEN_SENT
    return DeliveryCertainty.SENT_RESPONSE_LOST


def _declared_public_tool_names() -> tuple[str, ...]:
    return tuple(entry.tool_id for entry in project_registry())


def _declared_internal_capability_names() -> tuple[str, ...]:
    return tuple(
        sorted(
            capability.tool_name for capability in build_google_workspace_internal_capabilities()
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
    if any(not has_operation(tool_name) for tool_name in public_names):
        raise workspace_tools._WorkspaceToolError("CAPABILITY_SURFACE_MISMATCH")
    if any(not has_internal_operation(tool_name) for tool_name in internal_names):
        raise workspace_tools._WorkspaceToolError("CAPABILITY_SURFACE_MISMATCH")
    for tool_name in public_names | internal_names:
        google_workspace_tool_contract(tool_name)


class GoogleWorkspaceMcpServerEntrypoint:
    def run(self) -> None:
        run_server()


def main() -> None:
    GoogleWorkspaceMcpServerEntrypoint().run()


__all__ = ["GoogleWorkspaceMcpServerEntrypoint", "main", "run_server"]


if __name__ == "__main__":
    main()
