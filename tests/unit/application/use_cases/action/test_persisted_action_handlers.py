from __future__ import annotations

from json import dumps
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from google_work_agent.application.use_cases.action.modify_action import (
    ModifyActionCommand,
    ModifyActionHandler,
)
from google_work_agent.application.use_cases.action.prepare_write_retry import (
    PrepareWriteRetryCommand,
    PrepareWriteRetryHandler,
)
from google_work_agent.application.use_cases.action.reject_action import (
    RejectActionCommand,
    RejectActionHandler,
)
from google_work_agent.domain import (
    ActionCommand,
    ActionStatus,
    EffectType,
    ResultCode,
    calculate_canonical_json_hash,
)
from google_work_agent.ports import PlanReviewStatus, PlanStatus


def _uow() -> MagicMock:
    unit_of_work = MagicMock()
    unit_of_work.__enter__.return_value = unit_of_work
    unit_of_work.__exit__.return_value = None
    return unit_of_work


def _action(*, status: ActionStatus, version: int = 1) -> SimpleNamespace:
    arguments = {"payload": {"subject": "old"}}
    return SimpleNamespace(
        id="action-1",
        plan_id="plan-1",
        tool_name="test_write_tool",
        effect_type=EffectType.CREATE.value,
        status=status.value,
        version=version,
        arguments_json=dumps(arguments, sort_keys=True, separators=(",", ":")),
        arguments_hash=calculate_canonical_json_hash(arguments),
        risk={},
        target_resource_ref_id=None,
    )


def test_modify_persists_revocation_review_receipt_and_audit() -> None:
    unit_of_work = _uow()
    action = _action(status=ActionStatus.APPROVED)
    unit_of_work.command_receipts.get_by_command_id.side_effect = [None, None]
    unit_of_work.actions.get_by_id.return_value = action
    unit_of_work.evidence.list_by_action.return_value = [object()]
    unit_of_work.approvals.revoke_active_by_action.return_value = ("approval-1",)
    unit_of_work.actions.modify_write.return_value = SimpleNamespace(
        applied=True,
        result_code=ResultCode.TRANSITION_APPLIED,
        current_status=ActionStatus.MODIFIED,
        current_version=2,
        next_allowed_commands=(ActionCommand.APPROVE_ACTION,),
        conflict_detail=None,
    )
    unit_of_work.plans.get_by_id.return_value = SimpleNamespace(
        id="plan-1", run_id="run-1", review_status=PlanReviewStatus.REQUIRED
    )
    unit_of_work.plans.require_review.return_value = 7
    unit_of_work.action_dependencies.list_dependents.return_value = ()
    coordinator = MagicMock()
    handler = ModifyActionHandler(
        unit_of_work_factory=MagicMock(return_value=unit_of_work),
        now_ms=lambda: 1000,
        gateway=MagicMock(),
        local_run_coordinator=coordinator,
    )
    handler._registry = SimpleNamespace(
        require=lambda _tool_name: SimpleNamespace(modify_patchable_fields={"subject"})
    )

    result = handler(ModifyActionCommand(
        command_id="cmd-modify",
        request_hash="hash-modify",
        request_id="req-1",
        action_id=action.id,
        expected_version=1,
        arguments_patch={"subject": "new"},
    ))

    assert result.applied is True
    assert ActionCommand.APPROVE_ACTION.value not in result.next_allowed_commands
    unit_of_work.actions.modify_write.assert_called_once()
    unit_of_work.approvals.revoke_active_by_action.assert_called_once_with(action.id)
    unit_of_work.plans.require_review.assert_called_once_with(action.plan_id)
    unit_of_work.command_receipts.finish_json.assert_called_once()
    unit_of_work.traces.add.assert_called()
    unit_of_work.audits.add.assert_called()
    unit_of_work.commit.assert_called_once()
    coordinator.enqueue_resume.assert_called_once()


def _assert_terminal_modify_regression(
    *,
    initial_status: ActionStatus,
    initial_version: int,
    command_id: str,
) -> None:
    unit_of_work = _uow()
    action = _action(status=initial_status, version=initial_version)
    unit_of_work.command_receipts.get_by_command_id.side_effect = [None, None]
    unit_of_work.actions.get_by_id.return_value = action
    unit_of_work.evidence.list_by_action.return_value = [object()]
    unit_of_work.approvals.revoke_active_by_action.return_value = ("stale-approval",)
    unit_of_work.actions.modify_write.return_value = SimpleNamespace(
        applied=True,
        result_code=ResultCode.TRANSITION_APPLIED,
        current_status=ActionStatus.MODIFIED,
        current_version=initial_version + 1,
        next_allowed_commands=(ActionCommand.APPROVE_ACTION,),
        conflict_detail=None,
    )
    unit_of_work.plans.get_by_id.return_value = SimpleNamespace(
        id=action.plan_id,
        run_id="run-1",
        review_status=PlanReviewStatus.REQUIRED,
    )
    unit_of_work.plans.require_review.return_value = 12
    unit_of_work.action_dependencies.list_dependents.return_value = ()
    coordinator = MagicMock()
    handler = ModifyActionHandler(
        unit_of_work_factory=MagicMock(return_value=unit_of_work),
        now_ms=lambda: 1500,
        gateway=MagicMock(),
        local_run_coordinator=coordinator,
    )
    handler._registry = SimpleNamespace(
        require=lambda _tool_name: SimpleNamespace(modify_patchable_fields={"subject"})
    )

    result = handler(ModifyActionCommand(
        command_id=command_id,
        request_hash=f"hash-{command_id}",
        request_id=f"req-{command_id}",
        action_id=action.id,
        expected_version=initial_version,
        arguments_patch={"subject": "new"},
    ))

    expected_arguments = {"payload": {"subject": "new"}}
    assert result.applied is True
    assert result.action_status == ActionStatus.MODIFIED.value
    assert result.action_version == initial_version + 1
    assert ActionCommand.APPROVE_ACTION.value not in result.next_allowed_commands
    unit_of_work.actions.modify_write.assert_called_once_with(
        action.id,
        expected_version=initial_version,
        updated_at_ms=1500,
        arguments_json=dumps(expected_arguments, sort_keys=True, separators=(",", ":")),
        arguments_hash=calculate_canonical_json_hash(expected_arguments),
        risk=action.risk,
    )
    unit_of_work.approvals.revoke_active_by_action.assert_called_once_with(action.id)
    unit_of_work.approvals.insert.assert_not_called()
    unit_of_work.plans.require_review.assert_called_once_with(action.plan_id)
    unit_of_work.command_receipts.finish_json.assert_called_once()
    unit_of_work.traces.add.assert_called()
    unit_of_work.audits.add.assert_called()
    unit_of_work.commit.assert_called_once()
    coordinator.enqueue_resume.assert_called_once()
    assert unit_of_work.execution_attempts.method_calls == []
    assert unit_of_work.verifications.method_calls == []


def test_expired_modify_persists_modified_state_and_reopens_review() -> None:
    _assert_terminal_modify_regression(
        initial_status=ActionStatus.EXPIRED,
        initial_version=4,
        command_id="cmd-modify-expired",
    )


def test_failed_modify_persists_modified_state_without_execution_shortcut() -> None:
    _assert_terminal_modify_regression(
        initial_status=ActionStatus.FAILED,
        initial_version=5,
        command_id="cmd-modify-failed",
    )


def test_reject_persists_revocation_and_dependency_consequence() -> None:
    unit_of_work = _uow()
    action = _action(status=ActionStatus.APPROVED, version=2)
    dependent = SimpleNamespace(id="action-2", status=ActionStatus.APPROVED.value)
    unit_of_work.command_receipts.get_by_command_id.return_value = None
    unit_of_work.actions.get_by_id.side_effect = lambda action_id: action if action_id == action.id else dependent
    unit_of_work.plans.get_by_id.return_value = SimpleNamespace(
        id=action.plan_id, run_id="run-1", status=PlanStatus.WAITING_APPROVAL
    )
    unit_of_work.runs.get_by_id.return_value = SimpleNamespace(
        id="run-1", version=9, conversation_id="conversation-1"
    )
    unit_of_work.conversations.get.return_value = SimpleNamespace(account_id="acct-1")
    unit_of_work.approvals.revoke_active_by_action.return_value = ("approval-1",)
    unit_of_work.actions.reject_write.return_value = SimpleNamespace(
        applied=True,
        result_code=ResultCode.TRANSITION_APPLIED,
        current_status=ActionStatus.REJECTED,
        current_version=3,
        conflict_detail=None,
    )
    unit_of_work.action_dependencies.list_dependents.side_effect = lambda action_id: ("action-2",) if action_id == "action-1" else ()
    unit_of_work.actions.mark_dependency_blocked.return_value = True
    unit_of_work.actions.list_by_plan.return_value = [SimpleNamespace(status="PROPOSED")]

    result = RejectActionHandler(
        unit_of_work_factory=MagicMock(return_value=unit_of_work),
        now_ms=lambda: 2000,
    )(RejectActionCommand(
        command_id="cmd-reject",
        request_hash="hash-reject",
        action_id=action.id,
        expected_version=2,
        reason_code="USER_REJECTED",
    ))

    assert result.applied is True
    unit_of_work.actions.reject_write.assert_called_once()
    unit_of_work.actions.mark_dependency_blocked.assert_called_once()
    unit_of_work.command_receipts.finish_json.assert_called_once()
    unit_of_work.traces.add.assert_called()
    unit_of_work.audits.add.assert_called()
    unit_of_work.commit.assert_called_once()


def test_prepare_retry_preserves_prior_evidence_and_reopens_review() -> None:
    unit_of_work = _uow()
    action = _action(status=ActionStatus.FAILED, version=5)
    unit_of_work.command_receipts.get_by_command_id.return_value = None
    unit_of_work.actions.get_by_id.return_value = action
    unit_of_work.plans.get_by_id.return_value = SimpleNamespace(id=action.plan_id, run_id="run-1")
    unit_of_work.actions.prepare_write_retry.return_value = SimpleNamespace(
        applied=True,
        result_code=ResultCode.TRANSITION_APPLIED,
        current_status=ActionStatus.MODIFIED,
        current_version=6,
        next_allowed_commands=(ActionCommand.APPROVE_ACTION,),
        conflict_detail=None,
    )
    unit_of_work.plans.require_review.return_value = 11

    result = PrepareWriteRetryHandler(
        unit_of_work_factory=MagicMock(return_value=unit_of_work),
        now_ms=lambda: 3000,
    )(PrepareWriteRetryCommand(
        command_id="cmd-retry",
        request_hash="hash-retry",
        action_id=action.id,
        expected_action_version=5,
    ))

    assert result.applied is True
    assert result.action_status == ActionStatus.MODIFIED.value
    assert ActionCommand.APPROVE_ACTION.value not in result.next_allowed_commands
    assert unit_of_work.approvals.method_calls == []
    assert unit_of_work.execution_attempts.method_calls == []
    assert unit_of_work.verifications.method_calls == []
    unit_of_work.plans.require_review.assert_called_once_with(action.plan_id)
    unit_of_work.commit.assert_called_once()


@pytest.mark.parametrize("status", [ActionStatus.UNKNOWN_RESULT, ActionStatus.MISMATCH])
def test_prepare_retry_never_retries_uncertain_or_mismatch(status: ActionStatus) -> None:
    unit_of_work = _uow()
    action = _action(status=status, version=6)
    unit_of_work.command_receipts.get_by_command_id.return_value = None
    unit_of_work.actions.get_by_id.return_value = action
    unit_of_work.plans.get_by_id.return_value = SimpleNamespace(id=action.plan_id, run_id="run-1")

    result = PrepareWriteRetryHandler(
        unit_of_work_factory=MagicMock(return_value=unit_of_work),
        now_ms=lambda: 4000,
    )(PrepareWriteRetryCommand(
        command_id=f"cmd-{status.value.lower()}",
        request_hash="hash-safe",
        action_id=action.id,
        expected_action_version=6,
    ))

    assert result.applied is False
    assert result.action_status == status.value
    unit_of_work.actions.prepare_write_retry.assert_not_called()
    unit_of_work.plans.require_review.assert_not_called()
    assert unit_of_work.execution_attempts.method_calls == []
