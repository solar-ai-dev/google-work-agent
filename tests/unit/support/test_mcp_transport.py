import pytest

from google_work_agent.adapters.mcp import MCPGoogleWorkspaceGateway, SubprocessMCPTransport
from google_work_agent.ports import (
    DeliveryCertainty,
    GoogleWorkspaceGatewayError,
    MCPTransportError,
    MCPTransportErrorCode,
)
from tests.support.fakes import FakeMCPTransport, QueuedMCPFailure


def test_fake_mcp_transport_returns_queued_response_with_copy() -> None:
    transport = FakeMCPTransport()
    transport.queue_response({"schema_version": "v1", "items": [{"id": 1}]})

    response = transport.call_tool(tool_name="gmail_search_threads", arguments={"query": "project"})
    response.payload["items"].append({"id": 2})

    replay = FakeMCPTransport()
    replay.queue_response({"schema_version": "v1", "items": [{"id": 1}]})
    replay_response = replay.call_tool(
        tool_name="gmail_search_threads", arguments={"query": "project"}
    )

    assert replay_response.payload["items"] == [{"id": 1}]


def test_fake_mcp_transport_returns_queued_failure_without_retry() -> None:
    transport = FakeMCPTransport()
    transport.queue_failure(
        QueuedMCPFailure(code=MCPTransportErrorCode.CONNECTION_CLOSED, message="connection dropped")
    )

    try:
        transport.call_tool(tool_name="tasks_list_tasks", arguments={"tasklist_id": "x"})
    except MCPTransportError as error:
        assert error.code is MCPTransportErrorCode.CONNECTION_CLOSED
    else:
        raise AssertionError("expected MCP transport failure")

    assert len(transport.call_log) == 1


@pytest.mark.parametrize(
    ("code", "dispatch_started", "expected"),
    [
        (MCPTransportErrorCode.TIMEOUT, False, DeliveryCertainty.NOT_SENT),
        (MCPTransportErrorCode.TIMEOUT, True, DeliveryCertainty.MAY_HAVE_BEEN_SENT),
        (MCPTransportErrorCode.TOOL_REJECTED, True, DeliveryCertainty.MAY_HAVE_BEEN_SENT),
        (
            MCPTransportErrorCode.PROCESS_UNAVAILABLE,
            True,
            DeliveryCertainty.MAY_HAVE_BEEN_SENT,
        ),
    ],
)
def test_gateway_delivery_certainty_uses_transport_phase_not_exception_name(
    code: MCPTransportErrorCode,
    dispatch_started: bool,
    expected: DeliveryCertainty,
) -> None:
    transport = FakeMCPTransport()
    transport.queue_failure(
        QueuedMCPFailure(
            code=code,
            message="transport failed",
            dispatch_started=dispatch_started,
        )
    )

    with pytest.raises(GoogleWorkspaceGatewayError) as error_info:
        MCPGoogleWorkspaceGateway(transport=transport).create_task(
            task_list_id="task-list-default",
            payload={"title": "test"},
        )

    assert error_info.value.delivery_certainty is expected


def test_subprocess_partial_stdin_failure_is_typed_as_uncertain_delivery() -> None:
    class BrokenStdin:
        def write(self, value: str) -> int:
            del value
            raise BrokenPipeError("closed")

        def flush(self) -> None:
            raise AssertionError("flush must not run after write failure")

    class Process:
        stdin = BrokenStdin()

    transport = object.__new__(SubprocessMCPTransport)
    transport._process = Process()  # type: ignore[assignment]

    with pytest.raises(MCPTransportError) as error_info:
        transport._send_json({"type": "tool_call"})

    assert error_info.value.code is MCPTransportErrorCode.CONNECTION_CLOSED
    assert error_info.value.dispatch_started is True
