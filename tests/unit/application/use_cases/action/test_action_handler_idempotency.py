from __future__ import annotations

from json import dumps
from types import SimpleNamespace
from unittest.mock import MagicMock

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
from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.command_receipt.model import CommandReceiptStatus
from google_work_agent.domain.results import ResultCode


def _uow_with_receipt(response_json: str) -> MagicMock:
    unit_of_work = MagicMock()
    unit_of_work.__enter__.return_value = unit_of_work
    unit_of_work.__exit__.return_value = None
    unit_of_work.command_receipts.get_by_command_id.return_value = SimpleNamespace(
        command_id="cmd-1",
        command_type="test",
        request_hash="same-hash",
        aggregate_type="Action",
        aggregate_id="action-1",
        status=CommandReceiptStatus.APPLIED,
        result_code=ResultCode.TRANSITION_APPLIED,
        result_version=2,
        response=None,
        response_json=response_json,
        created_at_ms=1,
        completed_at_ms=2,
    )
    return unit_of_work


def test_modify_same__hash_receipt_replays__without_second_mutation() -> None:
    unit_of_work = _uow_with_receipt(
        dumps(
            {
                "applied": True,
                "result_code": ResultCode.TRANSITION_APPLIED.value,
                "action_id": "action-1",
                "action_status": ActionStatusV1.MODIFIED.value,
                "action_version": 2,
                "next_allowed_commands": [],
                "request_replayed": False,
                "conflict_detail": None,
            }
        )
    )
    result = ModifyActionHandler(
        unit_of_work_factory=MagicMock(return_value=unit_of_work),
        now_ms=lambda: 10,
        gateway=MagicMock(),
        checkpoint_port=MagicMock(),
        id_generator=MagicMock(),
        resume_target_registry=MagicMock(),
        schedule_run_execution=MagicMock(),
    )(
        ModifyActionCommand(
            command_id="cmd-1",
            request_hash="same-hash",
            request_id="req-1",
            action_id="action-1",
            expected_version=1,
            arguments_patch={"subject": "new"},
        )
    )
    assert result.request_replayed is True
    assert result.action_version == 2
    unit_of_work.actions.modify_write.assert_not_called()
    unit_of_work.command_receipts.add_received.assert_not_called()


def test_reject_same_hash__receipt_replays_without__second_reject_or_audit() -> None:
    unit_of_work = _uow_with_receipt(
        dumps(
            {
                "applied": True,
                "result_code": ResultCode.TRANSITION_APPLIED.value,
                "action_id": "action-1",
                "action_status": ActionStatusV1.REJECTED.value,
                "action_version": 2,
                "next_allowed_commands": [],
                "request_replayed": False,
                "conflict_detail": None,
            }
        )
    )
    result = RejectActionHandler(
        unit_of_work_factory=MagicMock(return_value=unit_of_work),
        now_ms=lambda: 10,
        checkpoint_port=MagicMock(),
        id_generator=MagicMock(),
        resume_target_registry=MagicMock(),
        schedule_run_execution=MagicMock(),
    )(
        RejectActionCommand(
            command_id="cmd-1",
            request_hash="same-hash",
            action_id="action-1",
            expected_version=1,
        )
    )
    assert result.request_replayed is True
    unit_of_work.actions.reject_write.assert_not_called()
    unit_of_work.audits.add.assert_not_called()
    unit_of_work.command_receipts.add_received.assert_not_called()


def test_prepare_retry_same__hash_receipt_replays__without_new_retry_attempt() -> None:
    unit_of_work = _uow_with_receipt(
        dumps(
            {
                "applied": True,
                "result_code": ResultCode.TRANSITION_APPLIED.value,
                "action_id": "action-1",
                "action_status": ActionStatusV1.MODIFIED.value,
                "action_version": 2,
                "next_allowed_commands": [],
                "approval_id": None,
                "attempt_id": None,
                "claim_token": None,
                "safe_error_code": None,
                "request_replayed": False,
                "conflict_detail": None,
            }
        )
    )
    result = PrepareWriteRetryHandler(
        unit_of_work_factory=MagicMock(return_value=unit_of_work),
        now_ms=lambda: 10,
        checkpoint_port=MagicMock(),
        id_generator=MagicMock(),
        resume_target_registry=MagicMock(),
        schedule_run_execution=MagicMock(),
    )(
        PrepareWriteRetryCommand(
            command_id="cmd-1",
            request_hash="same-hash",
            action_id="action-1",
            expected_action_version=1,
        )
    )
    assert result.request_replayed is True
    unit_of_work.actions.prepare_write_retry.assert_not_called()
    assert unit_of_work.execution_attempts.method_calls == []
    unit_of_work.workflow_handoffs.stage_pending.assert_not_called()
    unit_of_work.audits.append.assert_not_called()
    unit_of_work.command_receipts.add_received.assert_not_called()
