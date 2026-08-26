from google_work_agent.adapters.mcp.delivery_gateway import _delivery_aware_google_error
from google_work_agent.adapters.mcp.delivery_transport import (
    _delivery_certainty_from_error_payload,
)
from google_work_agent.ports import (
    DeliveryCertainty,
    MCPClientPortError,
    MCPClientPortErrorCode,
)


def test_transport_prefers_explicit_sent_response_lost_over_dispatch_boolean() -> None:
    certainty = _delivery_certainty_from_error_payload(
        {
            "delivery_certainty": "SENT_RESPONSE_LOST",
            "dispatch_started": False,
        }
    )

    assert certainty is DeliveryCertainty.SENT_RESPONSE_LOST


def test_gateway_preserves_sent_response_lost_exactly() -> None:
    transport_error = MCPClientPortError(
        code=MCPClientPortErrorCode.TOOL_REJECTED,
        message="REAUTH_REQUIRED",
        delivery_certainty=DeliveryCertainty.SENT_RESPONSE_LOST,
        request_id="req-1",
    )

    gateway_error = _delivery_aware_google_error(transport_error)

    assert gateway_error.delivery_certainty is DeliveryCertainty.SENT_RESPONSE_LOST
    assert gateway_error.mcp_request_id == "req-1"


def test_gateway_preserves_not_sent_exactly() -> None:
    transport_error = MCPClientPortError(
        code=MCPClientPortErrorCode.TOOL_REJECTED,
        message="REAUTH_REQUIRED",
        delivery_certainty=DeliveryCertainty.NOT_SENT,
        request_id="req-2",
    )

    gateway_error = _delivery_aware_google_error(transport_error)

    assert gateway_error.delivery_certainty is DeliveryCertainty.NOT_SENT
    assert gateway_error.mcp_request_id == "req-2"
