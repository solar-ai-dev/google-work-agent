"""Google Workspace MCP gateway with exact delivery-certainty propagation."""

from __future__ import annotations

from typing import Any, cast

from google_work_agent.adapters.mcp.gateway import (
    MCPGoogleWorkspaceGateway,
    _google_error_from_transport,
)
from google_work_agent.ports import (
    DeliveryCertainty,
    GoogleWorkspaceGatewayError,
    MCPTransportError,
)


class DeliveryAwareMCPGoogleWorkspaceGateway(MCPGoogleWorkspaceGateway):
    """Map typed MCP delivery certainty into the existing gateway error contract."""

    def _call(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, object]:
        try:
            response = self._transport.call_tool(tool_name=tool_name, arguments=arguments)
        except MCPTransportError as error:
            raise _delivery_aware_google_error(error) from error
        self._last_request_id = response.request_id
        return cast(dict[str, object], response.payload)


def _delivery_aware_google_error(error: MCPTransportError) -> GoogleWorkspaceGatewayError:
    mapped = _google_error_from_transport(error)
    certainty = error.delivery_certainty
    return GoogleWorkspaceGatewayError(
        code=mapped.code,
        message=str(mapped),
        delivered=certainty is not DeliveryCertainty.NOT_SENT,
        mutated=certainty is DeliveryCertainty.SENT_RESPONSE_LOST,
        mcp_request_id=error.request_id,
    )
