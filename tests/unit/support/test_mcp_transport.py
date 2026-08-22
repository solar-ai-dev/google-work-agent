from dataclasses import replace
from json import loads

import pytest

from google_work_agent.adapters.mcp import MCPGoogleWorkspaceGateway, SubprocessMCPTransport
from google_work_agent.ports.observability_events import ObservabilityContext
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


def test_mcp_call_tool_response_carries_a_request_id() -> None:
    """C: a real MCP request generates a request_id."""
    transport = FakeMCPTransport()
    transport.queue_response({"schema_version": "v1", "items": []})

    response = transport.call_tool(tool_name="gmail_search_threads", arguments={"query": "x"})

    assert response.request_id


def test_mcp_request_id_populates_observability_context_consistently() -> None:
    """D: the success response's request_id is exactly what
    ObservabilityContext.mcp_request_id should be populated from, and it
    is stable/consistent for that one call.
    """
    transport = FakeMCPTransport()
    transport.queue_response({"schema_version": "v1", "items": []})

    response = transport.call_tool(tool_name="gmail_search_threads", arguments={"query": "x"})
    context_a = ObservabilityContext(mcp_request_id=response.request_id)
    context_b = ObservabilityContext(mcp_request_id=response.request_id)

    assert context_a.mcp_request_id == response.request_id
    assert context_a == context_b


@pytest.mark.parametrize(
    "code",
    [MCPTransportErrorCode.TIMEOUT, MCPTransportErrorCode.CONNECTION_CLOSED],
)
def test_mcp_transport_error_carries_a_request_id_for_correlation(
    code: MCPTransportErrorCode,
) -> None:
    """E: MCP error/timeout is still traceable via the same mcp_request_id."""
    transport = FakeMCPTransport()
    transport.queue_failure(QueuedMCPFailure(code=code, message="failed", dispatch_started=True))

    with pytest.raises(MCPTransportError) as error_info:
        transport.call_tool(tool_name="gmail_search_threads", arguments={"query": "x"})

    assert error_info.value.request_id
    context = ObservabilityContext(mcp_request_id=error_info.value.request_id)
    assert context.mcp_request_id == error_info.value.request_id


def test_google_workspace_gateway_error_preserves_mcp_request_id() -> None:
    """E (gateway boundary): the domain-level GoogleWorkspaceGatewayError
    that Application/Connector code actually catches carries the
    originating mcp_request_id as a *typed* attribute -- not only hidden
    inside the message JSON string -- without adding a provider-specific
    field to the shared, provider-agnostic error type (mcp_request_id is
    transport-level correlation metadata, not a Google request id).
    """
    transport = FakeMCPTransport()
    transport.queue_failure(
        QueuedMCPFailure(
            code=MCPTransportErrorCode.TIMEOUT, message="failed", dispatch_started=True
        )
    )

    with pytest.raises(GoogleWorkspaceGatewayError) as error_info:
        MCPGoogleWorkspaceGateway(transport=transport).get_gmail_thread(thread_id="thread-1")

    assert error_info.value.mcp_request_id
    detail = loads(str(error_info.value))
    assert detail["mcp_request_id"] == error_info.value.mcp_request_id


def test_mcp_gateway_exposes_last_request_id_after_a_successful_call() -> None:
    """C (gateway boundary): a successful MCP-backed gateway call updates
    the typed last_request_id capability with the exact transport-assigned
    id, so an Application caller (e.g. VerifyWriteActionService) can read
    it immediately afterwards to correlate its own trace/audit write.
    """
    transport = FakeMCPTransport()
    transport.queue_response(
        {
            "item": {
                "fixture_snapshot_id": "snap-1",
                "resource_type": "gmail_thread",
                "resource_id": "thread-1",
                "parent_id": None,
                "related_resource_ids": [],
                "version": "1",
                "recovery_fingerprint": None,
                "payload": {"subject": "hello"},
            }
        }
    )
    gateway = MCPGoogleWorkspaceGateway(transport=transport)
    assert gateway.last_request_id is None

    gateway.get_gmail_thread(thread_id="thread-1")

    assert gateway.last_request_id is not None

    transport.queue_response(
        {
            "item": {
                "fixture_snapshot_id": "snap-2",
                "resource_type": "gmail_thread",
                "resource_id": "thread-1",
                "parent_id": None,
                "related_resource_ids": [],
                "version": "2",
                "recovery_fingerprint": None,
                "payload": {"subject": "hello again"},
            }
        }
    )
    first_request_id = gateway.last_request_id
    gateway.get_gmail_thread(thread_id="thread-1")

    # F: a second, distinct call updates it to a fresh id.
    assert gateway.last_request_id != first_request_id


def test_each_mcp_call_gets_a_fresh_request_id_while_run_correlation_stays_fixed() -> None:
    """F: a retry or a new call gets a new MCP request_id, while the
    existing Run/command-level correlation_id is untouched by that churn.
    """
    transport = FakeMCPTransport()
    transport.queue_response({"schema_version": "v1", "items": []})
    transport.queue_response({"schema_version": "v1", "items": []})

    first = transport.call_tool(tool_name="gmail_search_threads", arguments={"query": "x"})
    second = transport.call_tool(tool_name="gmail_search_threads", arguments={"query": "x"})

    assert first.request_id != second.request_id

    run_scoped_context = ObservabilityContext(run_id="run-1", command_id="command-1")
    first_context = replace(run_scoped_context, mcp_request_id=first.request_id)
    second_context = replace(run_scoped_context, mcp_request_id=second.request_id)

    assert first_context.run_id == second_context.run_id == "run-1"
    assert first_context.command_id == second_context.command_id == "command-1"
    assert first_context.mcp_request_id != second_context.mcp_request_id
