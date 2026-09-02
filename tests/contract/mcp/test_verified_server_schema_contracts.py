from __future__ import annotations

from typing import cast

import pytest

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    credential_provider as workspace_tools,
)
from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    entrypoint as verified_server,
)
from google_work_agent.ports.connector.contracts.google_workspace import DeliveryCertainty


def test_invalid_input__is_rejected__before_handler_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def forbidden_handler(
        state: workspace_tools.GoogleWorkspaceCredentialProvider,
        tool_name: str,
        arguments: dict[str, object],
    ) -> dict[str, object]:
        del state, tool_name, arguments
        calls.append("handler")
        return {}

    monkeypatch.setattr(verified_server, "dispatch_tool", forbidden_handler)
    state = cast(workspace_tools.GoogleWorkspaceCredentialProvider, object())

    with pytest.raises(verified_server._VerifiedToolContractError) as captured:
        verified_server._tool_call(
            state,
            tool_name="gmail_get_thread",
            arguments={},
        )

    assert captured.value.safe_code == "INVALID_ARGUMENT"
    assert captured.value.certainty is DeliveryCertainty.NOT_SENT
    assert calls == []


def test_read_output__contract_failure_is__uncertain_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def malformed_read(
        state: workspace_tools.GoogleWorkspaceCredentialProvider,
        tool_name: str,
        arguments: dict[str, object],
    ) -> dict[str, object]:
        del state, tool_name, arguments
        return {"item": {"resource_id": "thread-1"}}

    monkeypatch.setattr(verified_server, "dispatch_tool", malformed_read)
    state = cast(workspace_tools.GoogleWorkspaceCredentialProvider, object())

    with pytest.raises(verified_server._VerifiedToolContractError) as captured:
        verified_server._tool_call(
            state,
            tool_name="gmail_get_thread",
            arguments={"thread_id": "thread-1"},
        )

    assert captured.value.safe_code == "INVALID_MCP_OUTPUT"
    assert captured.value.certainty is DeliveryCertainty.MAY_HAVE_BEEN_SENT


def test_write_output__contract_failure_is__sent_response_lost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def malformed_write(
        state: workspace_tools.GoogleWorkspaceCredentialProvider,
        tool_name: str,
        arguments: dict[str, object],
    ) -> dict[str, object]:
        del state, tool_name, arguments
        calls.append("provider_write_returned")
        return {"item": {"resource_id": "task-1"}}

    monkeypatch.setattr(verified_server, "dispatch_tool", malformed_write)
    state = cast(workspace_tools.GoogleWorkspaceCredentialProvider, object())

    with pytest.raises(verified_server._VerifiedToolContractError) as captured:
        verified_server._tool_call(
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


def test_internal_read__output_failure_never__claims_write_mutation() -> None:
    assert (
        verified_server._output_contract_failure_certainty("gmail_get_attachment")
        is DeliveryCertainty.MAY_HAVE_BEEN_SENT
    )
