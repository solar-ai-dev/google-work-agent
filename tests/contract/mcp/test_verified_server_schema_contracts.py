from __future__ import annotations

from typing import cast

import pytest

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    server_runtime as verified_server,
)
from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    workspace_runtime as workspace_tools,
)
from google_work_agent.ports.connector.contracts.google_workspace import DeliveryCertainty


def test_invalid_input_is_rejected_before_handler_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def forbidden_handler(
        state: workspace_tools._WorkspaceState,
        arguments: dict[str, object],
    ) -> dict[str, object]:
        del state, arguments
        calls.append("handler")
        return {}

    monkeypatch.setattr(workspace_tools, "_gmail_get_thread", forbidden_handler)
    state = cast(workspace_tools._WorkspaceState, object())

    with pytest.raises(verified_server._VerifiedToolContractError) as captured:  # noqa: SLF001
        verified_server._tool_call(  # noqa: SLF001
            state,
            tool_name="gmail_get_thread",
            arguments={},
        )

    assert captured.value.safe_code == "INVALID_ARGUMENT"
    assert captured.value.certainty is DeliveryCertainty.NOT_SENT
    assert calls == []


def test_read_output_contract_failure_is_uncertain_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def malformed_read(
        state: workspace_tools._WorkspaceState,
        arguments: dict[str, object],
    ) -> dict[str, object]:
        del state, arguments
        return {"item": {"resource_id": "thread-1"}}

    monkeypatch.setattr(workspace_tools, "_gmail_get_thread", malformed_read)
    state = cast(workspace_tools._WorkspaceState, object())

    with pytest.raises(verified_server._VerifiedToolContractError) as captured:  # noqa: SLF001
        verified_server._tool_call(  # noqa: SLF001
            state,
            tool_name="gmail_get_thread",
            arguments={"thread_id": "thread-1"},
        )

    assert captured.value.safe_code == "INVALID_MCP_OUTPUT"
    assert captured.value.certainty is DeliveryCertainty.MAY_HAVE_BEEN_SENT


def test_write_output_contract_failure_is_sent_response_lost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def malformed_write(
        state: workspace_tools._WorkspaceState,
        arguments: dict[str, object],
    ) -> dict[str, object]:
        del state, arguments
        calls.append("provider_write_returned")
        return {"item": {"resource_id": "task-1"}}

    monkeypatch.setattr(workspace_tools, "_tasks_create_task", malformed_write)
    state = cast(workspace_tools._WorkspaceState, object())

    with pytest.raises(verified_server._VerifiedToolContractError) as captured:  # noqa: SLF001
        verified_server._tool_call(  # noqa: SLF001
            state,
            tool_name="tasks_create_task",
            arguments={
                "task_list_id": "list-1",
                "payload": {"title": "Task"},
                "claim_context": None,
            },
        )

    assert calls == ["provider_write_returned"]
    assert captured.value.safe_code == "INVALID_MCP_OUTPUT"
    assert captured.value.certainty is DeliveryCertainty.SENT_RESPONSE_LOST


def test_internal_read_output_failure_never_claims_write_mutation() -> None:
    assert (
        verified_server._output_contract_failure_certainty(  # noqa: SLF001
            "gmail_get_attachment"
        )
        is DeliveryCertainty.MAY_HAVE_BEEN_SENT
    )
