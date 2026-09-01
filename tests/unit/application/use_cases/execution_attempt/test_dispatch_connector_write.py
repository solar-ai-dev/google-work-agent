"""Issue #131 / 028-01: post-Begin cancel must not misclassify an
already-authorized in-flight dispatch as never started."""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from json import dumps
from types import SimpleNamespace
from typing import Any, cast

import pytest

from google_work_agent.application.use_cases.claim.build_claim_context import ClaimContextV2
from google_work_agent.application.use_cases.execution_attempt.dispatch_connector_write import (
    DispatchConnectorWriteCommandV1,
    DispatchConnectorWriteHandler,
    DispatchConnectorWriteResultV1,
)
from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.approval.model import ApprovalStatusV1
from google_work_agent.domain.canonical import calculate_canonical_json_hash
from google_work_agent.domain.command_receipt.model import CommandReceiptStatus
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.run.model import RunStatusV1
from google_work_agent.ports.connector.connector_write_port import ConnectorWriteResultV1

_TOOL_ARGUMENTS: dict[str, object] = {"task_list_id": "list-1", "payload": {"title": "Task"}}
_EXECUTION_ARGUMENTS_HASH = calculate_canonical_json_hash(_TOOL_ARGUMENTS)


class _Repository:
    def __init__(self, values: dict[str, object]) -> None:
        self._values = values

    def get(self, identity: str) -> object | None:
        return self._values.get(identity)


class _Plans:
    def __init__(self, plan: object) -> None:
        self._plan = plan

    def get_current(self, _run_id: str) -> object:
        return self._plan

    def load_bundle(self, _plan_id: str) -> object:
        return SimpleNamespace(plan=self._plan)


class _Receipts:
    def __init__(self, values: dict[str, _Receipt]) -> None:
        self._values = values

    def get_by_command_id(self, command_id: str) -> object | None:
        return self._values.get(command_id)


@dataclass(frozen=True, slots=True)
class _Receipt:
    status: CommandReceiptStatus
    response_json: str


class _UnitOfWork:
    def __init__(self, *, run_status: RunStatusV1) -> None:
        action = SimpleNamespace(
            id="action-1",
            plan_id="plan-1",
            status=ActionStatusV1.EXECUTING.value,
            connector_id="google_workspace",
            tool_name="tasks_create_task",
            arguments_hash="arguments-hash",
            effect_type="CREATE",
        )
        approval = SimpleNamespace(
            id="approval-1",
            action_id="action-1",
            status=ApprovalStatusV1.CONSUMED,
            canonical_arguments_hash="arguments-hash",
        )
        attempt = SimpleNamespace(
            id="attempt-1",
            approval_id="approval-1",
            status=ExecutionAttemptStatusV1.EXECUTING,
        )
        plan = SimpleNamespace(
            id="plan-1",
            run_id="run-1",
            status=PlanStatusV1.WAITING_APPROVAL,
            revision_no=1,
        )
        run = SimpleNamespace(id="run-1", status=run_status)
        receipt_response = dumps(
            {
                "applied": True,
                "attempt_id": "attempt-1",
                "attempt_status": ExecutionAttemptStatusV1.EXECUTING.value,
            },
            sort_keys=True,
        )
        receipts = {
            "begin-execution-attempt:attempt-1": _Receipt(
                status=CommandReceiptStatus.APPLIED, response_json=receipt_response
            )
        }
        self.execution_attempts = _Repository({"attempt-1": attempt})
        self.actions = _Repository({"action-1": action})
        self.approvals = _Repository({"approval-1": approval})
        self.plans = _Plans(plan)
        self.runs = _Repository({"run-1": run})
        self.command_receipts = _Receipts(receipts)

    def __enter__(self) -> _UnitOfWork:
        return self

    def __exit__(self, *args: object) -> None:
        return None


class _ToolRegistry:
    def bind_required(self, *_args: object, **_kwargs: object) -> object:
        return SimpleNamespace(tool_id="tasks_create_task")


class _ConnectorWritePort:
    def __init__(self) -> None:
        self.calls = 0

    def execute_write(self, *_args: object, **_kwargs: object) -> ConnectorWriteResultV1:
        self.calls += 1
        return ConnectorWriteResultV1(1, True, None, "provider-1", {}, None)


def _command() -> DispatchConnectorWriteCommandV1:
    claim_context = ClaimContextV2(
        claim_version=2,
        service_instance_id="service-1",
        mcp_process_instance_id="mcp-1",
        action_id="action-1",
        approval_id="approval-1",
        execution_attempt_id="attempt-1",
        tool_name="tasks_create_task",
        approval_arguments_hash="arguments-hash",
        execution_arguments_hash=_EXECUTION_ARGUMENTS_HASH,
        issued_at_ms=1,
        expires_at_ms=2,
        nonce="nonce-1",
        signature="signature-1",
    )
    return DispatchConnectorWriteCommandV1(
        action_id="action-1",
        approval_id="approval-1",
        execution_attempt_id="attempt-1",
        tool_id="tasks_create_task",
        tool_arguments=_TOOL_ARGUMENTS,
        claim_context=claim_context,
    )


def test_exact_canonical_contract_fields() -> None:
    assert tuple(field.name for field in fields(DispatchConnectorWriteCommandV1)) == (
        "action_id",
        "approval_id",
        "execution_attempt_id",
        "tool_id",
        "tool_arguments",
        "claim_context",
    )
    assert tuple(field.name for field in fields(DispatchConnectorWriteResultV1)) == (
        "connector_result",
    )


@pytest.mark.parametrize(
    "run_status",
    [RunStatusV1.WAITING_APPROVAL, RunStatusV1.VERIFYING, RunStatusV1.CANCEL_REQUESTED],
)
def test_already_authorized_dispatch_is_not_blocked_by_concurrent_run_status(
    run_status: RunStatusV1,
) -> None:
    port = _ConnectorWritePort()
    handler = DispatchConnectorWriteHandler(
        unit_of_work_factory=cast(Any, lambda: _UnitOfWork(run_status=run_status)),
        tool_registry=cast(Any, _ToolRegistry()),
        connector_write_port=cast(Any, port),
    )

    result = handler(_command())

    assert result.connector_result.success is True
    assert port.calls == 1


@pytest.mark.parametrize(
    "run_status",
    [
        RunStatusV1.PLANNING,
        RunStatusV1.COMPLETED,
        RunStatusV1.REAUTH_REQUIRED,
        RunStatusV1.RECOVERY_REQUIRED,
    ],
)
def test_dispatch_still_rejected_for_run_status_outside_the_closed_set(
    run_status: RunStatusV1,
) -> None:
    port = _ConnectorWritePort()
    handler = DispatchConnectorWriteHandler(
        unit_of_work_factory=cast(Any, lambda: _UnitOfWork(run_status=run_status)),
        tool_registry=cast(Any, _ToolRegistry()),
        connector_write_port=cast(Any, port),
    )

    with pytest.raises(PermissionError, match="no longer current"):
        handler(_command())

    assert port.calls == 0


def test_claim_attempt_mismatch_is_rejected_before_connector_io() -> None:
    port = _ConnectorWritePort()
    handler = DispatchConnectorWriteHandler(
        unit_of_work_factory=cast(
            Any, lambda: _UnitOfWork(run_status=RunStatusV1.WAITING_APPROVAL)
        ),
        tool_registry=cast(Any, _ToolRegistry()),
        connector_write_port=cast(Any, port),
    )
    command = _command()
    cross_wired = replace(
        command,
        claim_context=replace(command.claim_context, execution_attempt_id="attempt-other"),
    )

    with pytest.raises(PermissionError, match="identity binding mismatch"):
        handler(cross_wired)

    assert port.calls == 0
