from __future__ import annotations

from json import dumps, loads
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from tests.unit.application.use_cases._canonical_owner import assert_owner

from google_work_agent.application.use_cases.action import approve_action
from google_work_agent.application.use_cases.action.approve_action import (
    ApproveActionCommand,
    ApproveActionHandler,
)
from google_work_agent.domain.action.model import ActionStatusV1, EffectType
from google_work_agent.domain.canonical import calculate_canonical_json_hash
from google_work_agent.domain.plan.model import PlanReviewStatus, PlanStatusV1
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.run.model import RunStatusV1
from google_work_agent.ports.system.contracts.workflow_handoff import (
    MainControlResumeTargetV2,
    RunExecutionAcceptedV1,
)


def _handler(unit_of_work: MagicMock, id_generator: MagicMock) -> ApproveActionHandler:
    unit_of_work.checkpoints.load_workflow_binding.return_value = SimpleNamespace(
        langgraph_thread_id="thread-1",
        graph_profile="SIX_ROLE_BASELINE",
        graph_version="v1",
        requested_mode="AUTO",
    )
    unit_of_work.checkpoints.load_same_run_checkpoint.return_value = SimpleNamespace(
        checkpoint_id="checkpoint-1", checkpoint_generation=1
    )
    unit_of_work.workflow_handoffs.stage_pending.side_effect = lambda stage: SimpleNamespace(
        handoff_id=stage.handoff_id
    )
    return ApproveActionHandler(
        get_approval_ttl_minutes=lambda: 30,
        unit_of_work_factory=MagicMock(return_value=unit_of_work),
        now_ms=lambda: 1000,
        id_generator=id_generator,
        resume_target_registry=SimpleNamespace(
            issue_main_stage=lambda profile, stage, version: MainControlResumeTargetV2(
                "MAIN_CONTROL", stage, profile, version
            )
        ),
        schedule_run_execution=lambda command: RunExecutionAcceptedV1(1, True, "ACCEPTED"),
    )


def _action(*, status: ActionStatusV1 = ActionStatusV1.PROPOSED) -> SimpleNamespace:
    arguments = {"payload": {"to": ["person@example.com"], "subject": "Subject", "body": "Body"}}
    return SimpleNamespace(
        id="action-1",
        plan_id="plan-1",
        connector_id="google_workspace",
        tool_name="gmail_create_draft",
        effect_type=EffectType.CREATE.value,
        status=status.value,
        version=1,
        arguments_json=dumps(arguments, sort_keys=True, separators=(",", ":")),
        arguments_hash=calculate_canonical_json_hash(arguments),
        risk={},
        target_resource_ref_id="resource-ref-1",
    )


def _plan(
    *,
    status: PlanStatusV1 = PlanStatusV1.WAITING_APPROVAL,
    review_status: PlanReviewStatus = PlanReviewStatus.PASSED,
) -> SimpleNamespace:
    return SimpleNamespace(
        id="plan-1",
        run_id="run-1",
        revision_no=1,
        status=status,
        review_status=review_status,
        review_disposition="PASS" if review_status is PlanReviewStatus.PASSED else None,
        review_version=3,
    )


def _unit_of_work(
    *,
    action: SimpleNamespace | None = None,
    plan: SimpleNamespace | None = None,
    current_plan: SimpleNamespace | None = None,
    run_status: RunStatusV1 = RunStatusV1.WAITING_APPROVAL,
) -> MagicMock:
    unit_of_work = MagicMock()
    unit_of_work.__enter__.return_value = unit_of_work
    unit_of_work.__exit__.return_value = None
    action = action or _action()
    plan = plan or _plan()
    unit_of_work.command_receipts.get_by_command_id.return_value = None
    unit_of_work.actions.get.return_value = action
    unit_of_work.plans.load_bundle.return_value = SimpleNamespace(
        plan=plan, actions=(), dependencies=(), evidence=(), action_evidence=()
    )
    unit_of_work.plans.get_current.return_value = plan if current_plan is None else current_plan
    unit_of_work.runs.get.return_value = SimpleNamespace(
        id="run-1", conversation_id="conversation-1", status=run_status
    )
    unit_of_work.conversations.get.return_value = SimpleNamespace(account_id="acct-1")
    unit_of_work.resource_refs.get.return_value = SimpleNamespace(id="resource-ref-1")
    unit_of_work.actions.update_if_version_and_status.return_value = True
    unit_of_work.approvals.get_active_for_action.return_value = None
    return unit_of_work


def _command(**changes: object) -> ApproveActionCommand:
    values = {
        "command_id": "cmd-approve",
        "request_hash": "hash-approve",
        "request_id": "request-1",
        "action_id": "action-1",
        "expected_version": 1,
    }
    values.update(changes)
    return ApproveActionCommand(**values)  # type: ignore[arg-type]


def test_canonical_owner() -> None:
    assert_owner(
        "google_work_agent.application.use_cases.action.approve_action",
        ("ApproveActionCommand", "ApproveActionResult", "ApproveActionHandler"),
        "ApproveActionHandler",
    )


@pytest.mark.parametrize("status", (ActionStatusV1.PROPOSED, ActionStatusV1.MODIFIED))
def test_approve_persists_action_active_snapshot_receipt_and_exact_audit(
    monkeypatch: pytest.MonkeyPatch, status: ActionStatusV1
) -> None:
    action = _action(status=status)
    unit_of_work = _unit_of_work(action=action)
    id_generator = MagicMock()
    id_generator.new_uuid.side_effect = ["approval-1", "handoff-1"]
    snapshot = {"source_kind": "RESOURCE_REF", "resource_ref_id": "resource-ref-1"}
    build_snapshot = MagicMock(return_value=snapshot)
    monkeypatch.setattr(approve_action, "build_approval_source_snapshot", build_snapshot)

    result = _handler(unit_of_work, id_generator)(_command())

    assert result.applied is True
    assert result.action_status == ActionStatusV1.APPROVED.value
    unit_of_work.actions.update_if_version_and_status.assert_called_once()
    approval = unit_of_work.approvals.insert_active_snapshot.call_args.args[0]
    assert approval.id == "approval-1"
    assert approval.status.value == "ACTIVE"
    assert approval.approved_by_account_id == "acct-1"
    assert approval.action_version == 2
    assert approval.source_snapshot_hash == calculate_canonical_json_hash(snapshot)
    assert approval.canonical_arguments_hash == action.arguments_hash
    audit = unit_of_work.audits.append.call_args.args[0]
    assert audit.event_type == "ACTION_APPROVED"
    assert loads(audit.metadata_json)["approval_id"] == "approval-1"
    assert unit_of_work.traces.append.call_args.args[0].event_type == "WRITE_ACTION_APPROVED"
    assert id_generator.new_uuid.call_count == 2
    assert not id_generator.next_id.called
    unit_of_work.command_receipts.reserve_or_replay.assert_called_once()
    unit_of_work.command_receipts.store_result.assert_called_once()
    unit_of_work.workflow_handoffs.stage_pending.assert_called_once()
    unit_of_work.commit.assert_called_once()


@pytest.mark.parametrize(
    ("action", "command"),
    (
        (_action(), _command(expected_version=0)),
        (
            SimpleNamespace(**{**vars(_action()), "effect_type": EffectType.READ.value}),
            _command(),
        ),
    ),
)
def test_approve_rejects_stale_version_and_read_action(
    action: SimpleNamespace, command: ApproveActionCommand
) -> None:
    unit_of_work = _unit_of_work(action=action)
    result = _handler(unit_of_work, MagicMock())(command)

    assert result.applied is False
    unit_of_work.actions.update_if_version_and_status.assert_not_called()
    unit_of_work.approvals.insert_active_snapshot.assert_not_called()
    unit_of_work.workflow_handoffs.stage_pending.assert_not_called()


@pytest.mark.parametrize("reason", ("superseded", "noncurrent", "review"))
def test_approve_requires_current_waiting_plan_and_passed_review(reason: str) -> None:
    plan = _plan(
        status=PlanStatusV1.SUPERSEDED if reason == "superseded" else PlanStatusV1.WAITING_APPROVAL,
        review_status=PlanReviewStatus.REQUIRED if reason == "review" else PlanReviewStatus.PASSED,
    )
    current = _plan() if reason == "noncurrent" else plan
    if reason == "noncurrent":
        current.id = "plan-new"
    unit_of_work = _unit_of_work(plan=plan, current_plan=current)

    result = _handler(unit_of_work, MagicMock())(_command())

    assert result.applied is False
    assert result.result_code == ResultCode.STATE_CONFLICT.value
    unit_of_work.actions.update_if_version_and_status.assert_not_called()
    unit_of_work.approvals.insert_active_snapshot.assert_not_called()


@pytest.mark.parametrize("run_status", list(RunStatusV1))
def test_approve_application_matches_exact_parent_run_matrix(run_status: RunStatusV1) -> None:
    unit_of_work = _unit_of_work(run_status=run_status)
    id_generator = MagicMock()
    id_generator.new_uuid.side_effect = ["approval-1", "handoff-1"]

    result = _handler(unit_of_work, id_generator)(_command())

    assert result.applied is (run_status in {RunStatusV1.WAITING_APPROVAL, RunStatusV1.VERIFYING})


@pytest.mark.parametrize("repository", ("approvals", "audits"))
def test_approve_required_effect_failure_does_not_commit(repository: str) -> None:
    unit_of_work = _unit_of_work()
    if repository == "approvals":
        unit_of_work.approvals.insert_active_snapshot.side_effect = RuntimeError("approval failure")
    else:
        unit_of_work.audits.append.side_effect = RuntimeError("audit failure")
    id_generator = MagicMock()
    id_generator.new_uuid.side_effect = ["approval-1", "handoff-1"]
    handler = _handler(unit_of_work, id_generator)

    with pytest.raises(RuntimeError, match="failure"):
        handler(_command())

    unit_of_work.commit.assert_not_called()
    unit_of_work.command_receipts.store_result.assert_not_called()
    unit_of_work.workflow_handoffs.stage_pending.assert_not_called()
