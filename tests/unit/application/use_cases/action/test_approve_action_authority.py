from __future__ import annotations

from json import dumps
from types import SimpleNamespace
from unittest.mock import MagicMock

from google_work_agent.application.use_cases.action import approve_action
from google_work_agent.application.use_cases.action.approve_action import (
    ApproveActionCommand,
    ApproveActionHandler,
)
from google_work_agent.domain import (
    ActionCommand,
    ActionStatus,
    EffectType,
    ResultCode,
    calculate_canonical_json_hash,
)
from google_work_agent.ports import PlanReviewStatus, PlanStatus
from google_work_agent.ports.system.contracts.workflow_handoff import (
    MainControlResumeTargetV2,
    RunExecutionAcceptedV1,
)


def _handoff_dependencies(unit_of_work, id_generator):
    unit_of_work.checkpoints.load_workflow_binding.return_value = SimpleNamespace(
        langgraph_thread_id="thread-1", graph_profile="SIX_ROLE_BASELINE",
        graph_version="v1", requested_mode="AUTO"
    )
    unit_of_work.checkpoints.load_same_run_checkpoint.return_value = SimpleNamespace(
        checkpoint_id="checkpoint-1", checkpoint_generation=1
    )
    unit_of_work.workflow_handoffs.stage_pending.side_effect = lambda stage: SimpleNamespace(
        handoff_id=stage.handoff_id
    )
    return {
        "id_generator": id_generator,
        "resume_target_registry": SimpleNamespace(
            issue_main_stage=lambda profile, stage, version: MainControlResumeTargetV2(
                "MAIN_CONTROL", stage, profile, version
            )
        ),
        "schedule_run_execution": lambda command: RunExecutionAcceptedV1(
            1, True, "ACCEPTED"
        ),
    }


def test_approve_owns_persisted_source_snapshot_and_approval_construction(monkeypatch) -> None:
    unit_of_work = MagicMock()
    unit_of_work.__enter__.return_value = unit_of_work
    unit_of_work.__exit__.return_value = None
    arguments = {"payload": {"to": ["person@example.com"], "subject": "Subject", "body": "Body"}}
    action = SimpleNamespace(
        id="action-1",
        plan_id="plan-1",
        tool_name="gmail_create_draft",
        effect_type=EffectType.CREATE.value,
        status=ActionStatus.PROPOSED.value,
        version=1,
        arguments_json=dumps(arguments, sort_keys=True, separators=(",", ":")),
        arguments_hash=calculate_canonical_json_hash(arguments),
        risk={},
        target_resource_ref_id="resource-ref-1",
    )
    plan = SimpleNamespace(
        id="plan-1",
        run_id="run-1",
        status=PlanStatus.WAITING_APPROVAL,
        review_status=PlanReviewStatus.PASSED,
        review_version=3,
    )
    resource_ref = SimpleNamespace(id="resource-ref-1")
    unit_of_work.command_receipts.get_by_command_id.return_value = None
    unit_of_work.actions.get_by_id.return_value = action
    unit_of_work.plans.get_by_id.return_value = plan
    unit_of_work.runs.get_by_id.return_value = SimpleNamespace(
        id="run-1", conversation_id="conversation-1"
    )
    unit_of_work.conversations.get.return_value = SimpleNamespace(account_id="acct-1")
    unit_of_work.resource_refs.get.return_value = resource_ref
    unit_of_work.actions.approve_write.return_value = SimpleNamespace(
        applied=True,
        result_code=ResultCode.TRANSITION_APPLIED,
        current_status=ActionStatus.APPROVED,
        current_version=2,
        next_allowed_commands=(ActionCommand.REJECT_ACTION,),
        conflict_detail=None,
    )
    unit_of_work.approvals.list_by_action.return_value = []
    id_generator = MagicMock()
    id_generator.next_id.side_effect = ["approval-1", "handoff-1"]
    snapshot = {"source_kind": "RESOURCE_REF", "resource_ref_id": "resource-ref-1"}
    build_snapshot = MagicMock(return_value=snapshot)
    monkeypatch.setattr(approve_action, "build_approval_source_snapshot", build_snapshot)

    result = ApproveActionHandler(
        get_approval_ttl_minutes=lambda: 30,
        unit_of_work_factory=MagicMock(return_value=unit_of_work),
        now_ms=lambda: 1000,
        **_handoff_dependencies(unit_of_work, id_generator),
    )(
        ApproveActionCommand(
            command_id="cmd-approve",
            request_hash="hash-approve",
            request_id="request-1",
            action_id="action-1",
            expected_version=1,
        )
    )

    assert result.applied is True
    build_snapshot.assert_called_once_with(
        action=action,
        plan_run_id="run-1",
        resource_ref=resource_ref,
    )
    unit_of_work.actions.approve_write.assert_called_once_with(
        "action-1", expected_version=1, updated_at_ms=1000
    )
    approval = unit_of_work.approvals.insert.call_args.args[0]
    assert approval.id == "approval-1"
    assert approval.approved_by_account_id == "acct-1"
    assert approval.action_version == 2
    assert approval.source_snapshot_hash == calculate_canonical_json_hash(snapshot)
    assert approval.canonical_arguments_hash == action.arguments_hash
    assert approval.recovery_fingerprint
    unit_of_work.plans.activate_waiting.assert_called_once_with("plan-1")
    unit_of_work.command_receipts.add_received.assert_called_once()
    unit_of_work.command_receipts.finish_json.assert_called_once()
    unit_of_work.traces.add.assert_called_once()
    unit_of_work.audits.add.assert_called_once()
    unit_of_work.commit.assert_called_once()
    unit_of_work.workflow_handoffs.stage_pending.assert_called_once()


def test_approve_superseded_plan_child_has_zero_effect() -> None:
    unit_of_work = MagicMock()
    unit_of_work.__enter__.return_value = unit_of_work
    unit_of_work.__exit__.return_value = None
    action = SimpleNamespace(
        id="action-1",
        plan_id="plan-1",
        tool_name="gmail_create_draft",
        effect_type=EffectType.CREATE.value,
        status=ActionStatus.PROPOSED.value,
        version=1,
    )
    unit_of_work.command_receipts.get_by_command_id.return_value = None
    unit_of_work.actions.get_by_id.return_value = action
    unit_of_work.plans.get_by_id.return_value = SimpleNamespace(
        id="plan-1",
        run_id="run-1",
        status=PlanStatus.SUPERSEDED,
    )
    unit_of_work.runs.get_by_id.return_value = SimpleNamespace(
        id="run-1",
        conversation_id="conversation-1",
    )
    unit_of_work.conversations.get.return_value = SimpleNamespace(account_id="acct-1")

    result = ApproveActionHandler(
        get_approval_ttl_minutes=lambda: 30,
        unit_of_work_factory=MagicMock(return_value=unit_of_work),
        now_ms=lambda: 1000,
        **_handoff_dependencies(unit_of_work, MagicMock()),
    )(
        ApproveActionCommand(
            command_id="cmd-approve-superseded",
            request_hash="hash-approve-superseded",
            request_id="request-superseded",
            action_id="action-1",
            expected_version=1,
        )
    )

    assert result.applied is False
    assert result.result_code == ResultCode.STATE_CONFLICT.value
    assert result.conflict_detail == "superseded Plan children are history-only"
    unit_of_work.actions.approve_write.assert_not_called()
    unit_of_work.approvals.insert.assert_not_called()
    unit_of_work.plans.activate_waiting.assert_not_called()
