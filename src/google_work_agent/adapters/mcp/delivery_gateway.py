"""Google Workspace MCP gateway with exact delivery-certainty propagation."""

from __future__ import annotations

from json import dumps
from typing import Any, cast

from google_work_agent.adapters.mcp.gateway import (
    MCPGoogleWorkspaceGateway as _CompatibilityGateway,
)
from google_work_agent.ports import (
    DeliveryCertainty,
    GoogleWorkspaceErrorCode,
    GoogleWorkspaceGatewayError,
    MCPClientPortError,
    MCPClientPortErrorCode,
)


class DeliveryAwareMCPGoogleWorkspaceGateway(_CompatibilityGateway):
    """Preserve typed MCP delivery certainty into the Workspace gateway error."""

    def _call(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, object]:
        try:
            response = self._transport.call_tool(tool_name=tool_name, arguments=arguments)
        except MCPClientPortError as error:
            raise _delivery_aware_google_error(error) from error
        self._last_request_id = response.request_id
        return cast(dict[str, object], response.payload)


def _delivery_aware_google_error(error: MCPClientPortError) -> GoogleWorkspaceGatewayError:
    tool_error_map = {
        "INVALID_ARGUMENT": GoogleWorkspaceErrorCode.INVALID_ARGUMENT,
        "REAUTH_REQUIRED": GoogleWorkspaceErrorCode.AUTH_EXPIRED,
        "OAUTH_NOT_CONNECTED": GoogleWorkspaceErrorCode.AUTH_EXPIRED,
        "PERMISSION_DENIED": GoogleWorkspaceErrorCode.PERMISSION_DENIED,
        "NOT_FOUND": GoogleWorkspaceErrorCode.NOT_FOUND,
        "RATE_LIMITED": GoogleWorkspaceErrorCode.RATE_LIMITED,
        "UPSTREAM_5XX": GoogleWorkspaceErrorCode.UPSTREAM_5XX,
        "TIMEOUT": GoogleWorkspaceErrorCode.TIMEOUT,
        "INVALID_MCP_OUTPUT": GoogleWorkspaceErrorCode.RESPONSE_MALFORMED,
        "MCP_UNAVAILABLE": GoogleWorkspaceErrorCode.CONNECTION_CLOSED,
    }
    code_map = {
        MCPClientPortErrorCode.TIMEOUT: GoogleWorkspaceErrorCode.TIMEOUT,
        MCPClientPortErrorCode.CONNECTION_CLOSED: GoogleWorkspaceErrorCode.CONNECTION_CLOSED,
        MCPClientPortErrorCode.PROCESS_UNAVAILABLE: GoogleWorkspaceErrorCode.CONNECTION_CLOSED,
        MCPClientPortErrorCode.NOT_FOUND: GoogleWorkspaceErrorCode.NOT_FOUND,
        MCPClientPortErrorCode.SCHEMA_MISMATCH: GoogleWorkspaceErrorCode.RESPONSE_MALFORMED,
        MCPClientPortErrorCode.MALFORMED_RESPONSE: GoogleWorkspaceErrorCode.RESPONSE_MALFORMED,
        MCPClientPortErrorCode.TOOL_REJECTED: GoogleWorkspaceErrorCode.PERMISSION_DENIED,
        MCPClientPortErrorCode.HANDSHAKE_FAILED: GoogleWorkspaceErrorCode.CONNECTION_CLOSED,
        MCPClientPortErrorCode.ARTIFACT_REJECTED: GoogleWorkspaceErrorCode.CONNECTION_CLOSED,
        MCPClientPortErrorCode.CONFIGURATION_ERROR: GoogleWorkspaceErrorCode.CONNECTION_CLOSED,
    }
    certainty = error.delivery_certainty
    return GoogleWorkspaceGatewayError(
        code=tool_error_map.get(str(error), code_map[error.code]),
        message=dumps(
            {
                "safe_error": error.code.value,
                "detail": str(error),
                "mcp_request_id": error.request_id,
                "delivery_certainty": certainty.value,
            },
            sort_keys=True,
        ),
        delivered=certainty is not DeliveryCertainty.NOT_SENT,
        mutated=certainty is DeliveryCertainty.SENT_RESPONSE_LOST,
        mcp_request_id=error.request_id,
    )


__all__ = ["DeliveryAwareMCPGoogleWorkspaceGateway"]
