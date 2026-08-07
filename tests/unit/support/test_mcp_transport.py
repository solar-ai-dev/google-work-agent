from google_work_agent.ports import MCPTransportError, MCPTransportErrorCode
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
