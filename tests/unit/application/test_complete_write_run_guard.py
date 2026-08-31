from __future__ import annotations

from dataclasses import replace
from typing import cast

import pytest

from google_work_agent.application.use_cases.run.complete_write_run import CompleteWriteRunHandler
from google_work_agent.domain.action.model import Action as ActionRecord
from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.approval.model import Approval as ApprovalRecord
from google_work_agent.domain.approval.model import ApprovalStatusV1
from google_work_agent.domain.execution_attempt.model import (
    ExecutionAttempt as ExecutionAttemptRecord,
)
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.plan.model import Plan as PlanRecord
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.verification.model import Verification as VerificationRecord
from google_work_agent.domain.verification.model import VerificationStatus
from google_work_agent.ports.persistence.command_receipt_repository import (
    CommandReceiptRepository,
)
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


class _CancelReader:
    def __init__(self, active: bool = False) -> None:
        self.active = active

    def has_durable_cancel_intent(self, _run_id: str) -> bool:
        return self.active


class _ListRepo:
    def __init__(self, values: tuple[object, ...]) -> None:
        self.values = values

    def list_for_action(self, _action_id: str) -> tuple[object, ...]:
        return self.values

    def get_active_for_approval(self, approval_id: str) -> object | None:
        return next(
            (
                item
                for item in self.values
                if getattr(item, "approval_id", None) == approval_id
                and getattr(item, "status", None)
                in {
                    ExecutionAttemptStatusV1.CLAIMED,
                    ExecutionAttemptStatusV1.EXECUTING,
                    ExecutionAttemptStatusV1.UNKNOWN_RESULT,
                }
            ),
            None,
        )


class _GuardUow:
    def __init__(
        self,
        *,
        approvals: tuple[ApprovalRecord, ...],
        attempts: tuple[ExecutionAttemptRecord, ...],
        verifications: tuple[VerificationRecord, ...],
    ) -> None:
        self.approvals = _ListRepo(cast(tuple[object, ...], approvals))
        self.approvals = self.approvals
        self.execution_attempts = _ListRepo(cast(tuple[object, ...], attempts))
        self.verifications = _ListRepo(cast(tuple[object, ...], verifications))


def _plan(status: PlanStatusV1 = PlanStatusV1.WAITING_APPROVAL) -> PlanRecord:
    return PlanRecord(
        id="plan-1",
        run_id="run-1",
        revision_no=1,
        status=status,
        summary_text="write",
        created_at_ms=1,
    )


def _action(status: ActionStatusV1 = ActionStatusV1.VERIFIED) -> ActionRecord:
    return ActionRecord(
        id="action-1",
        plan_id="plan-1",
        connector_id="google_workspace",
        position=0,
        tool_name="tasks_create_task",
        effect_type="CREATE",
        approval_requirement="REQUIRED",
        verification_policy="GET_COMPARE",
        recovery_policy="RESOURCE_SEARCH",
        target_resource_ref_id=None,
        status=status.value,
        arguments_json="{}",
        arguments_hash="hash",
        expected_json="{}",
        risk={},
        version=4,
        created_at_ms=1,
        updated_at_ms=2,
    )


def _approval(status: ApprovalStatusV1 = ApprovalStatusV1.CONSUMED) -> ApprovalRecord:
    return ApprovalRecord(
        id="approval-1",
        action_id="action-1",
        approval_no=1,
        action_version=1,
        status=status,
        approved_by_account_id="acct-1",
        approved_by_display=None,
        arguments_snapshot_json="{}",
        canonical_arguments_hash="hash",
        source_snapshot_json="{}",
        source_snapshot_hash="source-hash",
        policy_version="policy-v1",
        tool_schema_version="schema-v1",
        idempotency_key="idem-1",
        recovery_fingerprint="recovery-1",
        approved_at_ms=1,
        expires_at_ms=1_800_001,
        consumed_at_ms=2,
    )


def _attempt(
    status: ExecutionAttemptStatusV1 = ExecutionAttemptStatusV1.SUCCEEDED,
) -> ExecutionAttemptRecord:
    return ExecutionAttemptRecord(
        id="attempt-1",
        approval_id="approval-1",
        attempt_no=1,
        status=status,
        version=1,
        result_resource_ref_id="resource-1",
        response_metadata_json="{}",
        error_code=None,
        error_detail_json=None,
        started_at_ms=2,
        finished_at_ms=3,
    )


def _verification(
    status: VerificationStatus = VerificationStatus.VERIFIED,
) -> VerificationRecord:
    return VerificationRecord(
        id="verification-1",
        execution_attempt_id="attempt-1",
        verification_no=1,
        status=status,
        normalizer_version="v1",
        expected_json="{}",
        actual_json="{}",
        diff_json="{}",
        verified_at_ms=4,
    )


def _conflict(
    *,
    action: ActionRecord | None = None,
    plan: PlanRecord | None = None,
    approval: ApprovalRecord | None = None,
    attempt: ExecutionAttemptRecord | None = None,
    verification: VerificationRecord | None = None,
    cancel: bool = False,
) -> str | None:
    selected_plan = plan or _plan()
    selected_action = action or _action()
    selected_approval = approval or _approval()
    selected_attempt = attempt or _attempt()
    selected_verification = verification or _verification()
    uow = _GuardUow(
        approvals=(selected_approval,),
        attempts=(selected_attempt,),
        verifications=(selected_verification,),
    )
    return CompleteWriteRunHandler._aggregate_conflict(
        unit_of_work=cast(UnitOfWork, uow),
        run_id="run-1",
        relevant_plans=(selected_plan,),
        plan=selected_plan,
        actions=(selected_action,),
        cancel_reader=cast(CommandReceiptRepository, _CancelReader(cancel)),
    )


@pytest.mark.parametrize(
    ("status", "expected_fragment"),
    [
        (ActionStatusV1.UNKNOWN_RESULT, "UNKNOWN_RESULT"),
        (ActionStatusV1.EXECUTED, "verified"),
        (ActionStatusV1.MISMATCH, "MISMATCH"),
        (ActionStatusV1.FAILED, "FAILED"),
        (ActionStatusV1.APPROVED, "not VERIFIED"),
    ],
)
def test_complete_write_run_rejects_unresolved_action_states(
    status: ActionStatusV1,
    expected_fragment: str,
) -> None:
    detail = _conflict(action=_action(status))

    assert detail is not None
    assert expected_fragment in detail


def test_complete_write_run_rejects_durable_cancel_intent() -> None:
    assert "cancel intent" in cast(str, _conflict(cancel=True))


def test_complete_write_run_rejects_illegal_active_approval() -> None:
    detail = _conflict(approval=replace(_approval(), status=ApprovalStatusV1.ACTIVE))

    assert detail is not None
    assert "ACTIVE approval" in detail


@pytest.mark.parametrize(
    "status",
    [
        ExecutionAttemptStatusV1.CLAIMED,
        ExecutionAttemptStatusV1.EXECUTING,
        ExecutionAttemptStatusV1.UNKNOWN_RESULT,
    ],
)
def test_complete_write_run_rejects_unresolved_attempt(status: ExecutionAttemptStatusV1) -> None:
    detail = _conflict(attempt=replace(_attempt(), status=status))

    assert detail is not None
    assert "unresolved execution attempt" in detail


def test_complete_write_run_rejects_unverified_verification() -> None:
    detail = _conflict(verification=replace(_verification(), status=VerificationStatus.MISMATCH))

    assert detail is not None
    assert "verification is unresolved" in detail


def test_complete_write_run_accepts_only_fully_verified_resolved_aggregate() -> None:
    assert _conflict() is None


def test_complete_write_run_rejects_legacy_read_active_plan() -> None:
    assert "WAITING_APPROVAL" in cast(str, _conflict(plan=_plan(PlanStatusV1.ACTIVE)))


def test_complete_write_run_rejects_multiple_non_superseded_plans() -> None:
    plan = _plan()
    uow = _GuardUow(
        approvals=(_approval(),),
        attempts=(_attempt(),),
        verifications=(_verification(),),
    )

    detail = CompleteWriteRunHandler._aggregate_conflict(
        unit_of_work=cast(UnitOfWork, uow),
        run_id="run-1",
        relevant_plans=(plan, replace(plan, id="plan-2", revision_no=2)),
        plan=None,
        actions=(),
        cancel_reader=cast(CommandReceiptRepository, _CancelReader(False)),
    )

    assert detail == "write completion requires exactly one non-superseded plan"
