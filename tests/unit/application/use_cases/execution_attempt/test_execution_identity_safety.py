from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.application.use_cases.execution_attempt.mark_failed import (
    MarkFailedCommand,
    MarkFailedHandler,
)
from google_work_agent.application.use_cases.execution_attempt.resolve_as_failed import (
    ResolveAsFailedCommand,
    ResolveAsFailedHandler,
)
from google_work_agent.application.use_cases.run.begin_verification import (
    BeginVerificationCommand,
    BeginVerificationHandler,
)
from google_work_agent.application.use_cases.verification.verify_effect import (
    VerifyEffectHandler,
    VerifyEffectQueryV1,
)
from google_work_agent.domain.action.model import Action, ActionStatusV1
from google_work_agent.domain.approval.model import Approval, ApprovalStatusV1
from google_work_agent.domain.command_receipt.model import (
    CommandReceipt,
    CommandReceiptStatus,
)
from google_work_agent.domain.execution_attempt.model import (
    ExecutionAttempt,
    ExecutionAttemptStatusV1,
)
from google_work_agent.domain.plan.model import Plan, PlanStatusV1
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.run.model import Run, RunStatusV1
from google_work_agent.ports.connector.contracts.google_workspace import DeliveryCertainty


class _Repository:
    def __init__(self, values: dict[str, object]) -> None:
        self._values = values

    def get(self, identity: str) -> object | None:
        return self._values.get(identity)


class _Plans:
    def __init__(self, plan: Plan) -> None:
        self._plan = plan

    def get_current(self, _run_id: str) -> Plan:
        return self._plan

    def load_bundle(self, plan_id: str) -> object | None:
        return SimpleNamespace(plan=self._plan) if plan_id == self._plan.id else None


class _Receipts:
    def __init__(self, values: dict[str, CommandReceipt] | None = None) -> None:
        self._values = values or {}
        self.reserve_calls = 0

    def get_by_command_id(self, command_id: str) -> CommandReceipt | None:
        return self._values.get(command_id)

    def reserve_or_replay(self, **_kwargs: object) -> None:
        self.reserve_calls += 1
        raise AssertionError("invalid identity must be rejected before receipt mutation")


class _UnitOfWork:
    def __init__(
        self,
        *,
        action: Action,
        approval: Approval,
        attempt: ExecutionAttempt,
        receipts: _Receipts | None = None,
    ) -> None:
        plan = Plan(
            "plan-1",
            "run-1",
            1,
            PlanStatusV1.WAITING_APPROVAL,
            "write",
            1,
        )
        run = Run(
            "run-1",
            "conversation-1",
            RunStatusV1.WAITING_APPROVAL,
            0,
            1,
            None,
        )
        self.actions = _Repository({action.id: action})
        self.approvals = _Repository({approval.id: approval})
        self.execution_attempts = _Repository({attempt.id: attempt})
        self.plans = _Plans(plan)
        self.runs = _Repository({run.id: run})
        self.command_receipts = receipts or _Receipts()
        self.commit_calls = 0

    def __enter__(self) -> _UnitOfWork:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def commit(self) -> None:
        self.commit_calls += 1


class _ConnectorRead:
    def __init__(self) -> None:
        self.calls = 0

    def execute_read(self, *_args: object, **_kwargs: object) -> object:
        self.calls += 1
        raise AssertionError("stale verification must be rejected before connector I/O")


def _action(status: ActionStatusV1 = ActionStatusV1.EXECUTING) -> Action:
    return Action(
        "action-1",
        "plan-1",
        "google_workspace",
        0,
        "tasks_create_task",
        "CREATE",
        "REQUIRED",
        "GET_COMPARE",
        "RESOURCE_SEARCH",
        None,
        status.value,
        "{}",
        "a" * 64,
        "{}",
        {},
        2,
        1,
        1,
    )


def _approval(*, action_id: str = "action-1") -> Approval:
    return Approval(
        "approval-1",
        action_id,
        1,
        1,
        ApprovalStatusV1.CONSUMED,
        "account-1",
        None,
        "{}",
        "a" * 64,
        "{}",
        "b" * 64,
        "policy-v1",
        "schema-v1",
        "c" * 64,
        "d" * 64,
        1,
        100,
        2,
    )


def _attempt(
    status: ExecutionAttemptStatusV1 = ExecutionAttemptStatusV1.EXECUTING,
) -> ExecutionAttempt:
    return ExecutionAttempt(
        "attempt-1",
        "approval-1",
        1,
        status,
        1,
        None,
        None,
        None,
        None,
        2,
        None,
    )


def test_cross_wired_action__attempt_is_rejected__before_receipt_mutation() -> None:
    receipts = _Receipts()
    unit_of_work = _UnitOfWork(
        action=_action(),
        approval=_approval(action_id="action-other"),
        attempt=_attempt(),
        receipts=receipts,
    )
    handler = MarkFailedHandler(
        unit_of_work_factory=cast(Any, lambda: unit_of_work),
        now_ms=lambda: 10,
    )

    with pytest.raises(ValueError, match="binding mismatch"):
        handler(
            MarkFailedCommand(
                "mark-failed-1",
                "e" * 64,
                "action-1",
                "attempt-1",
                2,
                1,
                DeliveryCertainty.NOT_SENT,
                "NOT_SENT",
                "not sent",
            )
        )

    assert receipts.reserve_calls == 0
    assert unit_of_work.commit_calls == 0


def test_stale_attempt__verification_is_rejected__before_connector_io() -> None:
    connector = _ConnectorRead()
    unit_of_work = _UnitOfWork(
        action=_action(ActionStatusV1.EXECUTED),
        approval=_approval(),
        attempt=_attempt(ExecutionAttemptStatusV1.FAILED),
    )
    handler = VerifyEffectHandler(
        connector_read=cast(Any, connector),
        tool_registry=load_signed_tool_registry(),
        unit_of_work_factory=cast(Any, lambda: unit_of_work),
    )

    with pytest.raises(ValueError, match="current succeeded"):
        handler(
            VerifyEffectQueryV1(
                "run-1",
                "action-1",
                "attempt-1",
                "CREATE",
                {},
                None,
            )
        )

    assert connector.calls == 0


def test_begin_verification__rejects_stale__attempt_before_mutation() -> None:
    receipts = _Receipts()
    unit_of_work = _UnitOfWork(
        action=_action(ActionStatusV1.EXECUTED),
        approval=_approval(),
        attempt=_attempt(ExecutionAttemptStatusV1.FAILED),
        receipts=receipts,
    )
    handler = BeginVerificationHandler(
        unit_of_work_factory=cast(Any, lambda: unit_of_work),
        checkpoint_port=cast(Any, object()),
        now_ms=lambda: 10,
        resume_target_registry=cast(Any, object()),
    )

    with pytest.raises(ValueError, match="current executed"):
        handler(
            BeginVerificationCommand(
                "begin-verification-1",
                "f" * 64,
                "run-1",
                "action-1",
                "attempt-1",
            )
        )

    assert receipts.reserve_calls == 0
    assert unit_of_work.commit_calls == 0


@pytest.mark.parametrize("proof_attempt_id", [None, "attempt-other"])
def test_resolve_as__failed_requires_same__attempt_durable_proof(
    proof_attempt_id: str | None,
) -> None:
    proof_id = "lookup-proof-1"
    proof_hash = "b" * 64
    receipt = (
        None
        if proof_attempt_id is None
        else CommandReceipt(
            proof_id,
            "LookupUnknownResult",
            proof_hash,
            "ExecutionAttempt",
            proof_attempt_id,
            CommandReceiptStatus.APPLIED,
            ResultCode.TRANSITION_APPLIED,
            None,
            None,
            "{}",
            1,
            2,
        )
    )
    receipts = _Receipts({} if receipt is None else {proof_id: receipt})
    unit_of_work = _UnitOfWork(
        action=_action(ActionStatusV1.UNKNOWN_RESULT),
        approval=_approval(),
        attempt=_attempt(ExecutionAttemptStatusV1.UNKNOWN_RESULT),
        receipts=receipts,
    )
    handler = ResolveAsFailedHandler(
        unit_of_work_factory=cast(Any, lambda: unit_of_work),
        now_ms=lambda: 10,
    )

    with pytest.raises(ValueError, match="same-Attempt lookup proof"):
        handler(
            ResolveAsFailedCommand(
                "resolve-failed-1",
                "c" * 64,
                "action-1",
                "attempt-1",
                2,
                1,
                proof_id,
                proof_hash,
                "NOT_EXECUTED",
                "not executed",
            )
        )

    assert receipts.reserve_calls == 0
    assert unit_of_work.commit_calls == 0
