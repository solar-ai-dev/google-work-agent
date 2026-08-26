"""GAP-F2 vertical slice: Action Modify carries a real arguments_patch.

Covers the full Modify contract end to end against real SQLite persistence:
PROPOSED/APPROVED edits, Approval revoke, Tool Schema field allowlisting,
version conflict, command replay, and Canonical Arguments hash integrity.
"""

from json import loads
from pathlib import Path

import pytest

from google_work_agent.adapters.connectors.google_workspace import GOOGLE_WORKSPACE_CONNECTOR_ID
from google_work_agent.adapters.persistence import (
    apply_migrations,
    connect_sqlite,
    sqlite_unit_of_work_factory,
)
from google_work_agent.application.write_action_mutation import ModifyWriteActionService
from google_work_agent.application.write_action_mutation_contracts import (
    ModifyWriteActionCommand,
)
from google_work_agent.application.write_approval import ApproveWriteActionService
from google_work_agent.application.write_approval_contracts import (
    ApproveWriteActionCommand,
)
from google_work_agent.application.write_claim import ClaimWriteActionService
from google_work_agent.application.write_execution_contracts import (
    ClaimWriteActionCommand,
)
from google_work_agent.application.write_plan import (
    PublishWritePlanService,
    SaveWritePlanService,
)
from google_work_agent.application.write_plan_contracts import (
    PublishWritePlanCommand,
    SaveWritePlanCommand,
    WriteActionDraft,
    WriteEvidenceDraft,
)
from google_work_agent.domain.action.model import ActionStatus
from google_work_agent.domain.approval.model import ApprovalStatus
from google_work_agent.domain.canonical import (
    calculate_canonical_json_hash,
    canonicalize_json_value,
)
from google_work_agent.domain.evidence.model import EvidenceOriginType
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatus
from google_work_agent.domain.plan.model import PlanReviewStatus
from google_work_agent.domain.results import ResultCode
from google_work_agent.ports import ResourcePage, ResourceSnapshot, ResourceType
from tests.support.fakes import FakeClockPort

_TASK_PAYLOAD = {"title": "Send summary", "notes": "draft notes"}


class _EmptyTaskListGateway:
    def list_tasks(
        self,
        *,
        task_list_id: str,
        page_token: str | None,
        page_size: int,
    ) -> ResourcePage:
        del task_list_id, page_token, page_size
        return ResourcePage(items=(), next_page_token=None)


_EMPTY_TASK_LIST_GATEWAY = _EmptyTaskListGateway()


@pytest.fixture()
def modify_database(tmp_path: Path) -> Path:
    database_path = tmp_path / "modify-actions.db"
    connection = connect_sqlite(database_path)
    try:
        apply_migrations(connection, now_ms=lambda: 1)
        connection.execute(
            """
            INSERT INTO google_accounts (id, email, display_name, connected_at_ms)
            VALUES ('account-1', 'user@example.com', 'User', 1);
            """
        )
        connection.execute(
            """
            INSERT INTO conversations (id, account_id, title, created_at_ms, updated_at_ms)
            VALUES ('conversation-1', 'account-1', 'Conversation', 1, 1);
            """
        )
        connection.execute(
            """
            INSERT INTO runs (
                id, conversation_id, entry_mode, status, langgraph_thread_id,
                requested_mode, budget_json, version, started_at_ms
            )
            VALUES (
                'run-1', 'conversation-1', 'AGENT_SEARCH', 'PLANNING', 'thread-1',
                'AUTO', '{}', 0, 100
            );
            """
        )
    finally:
        connection.close()
    return database_path


def _save_and_publish_task_action(
    *, database_path: Path, clock: FakeClockPort, action_id: str, plan_id: str
) -> None:
    unit_of_work_factory = sqlite_unit_of_work_factory(database_path)
    save_service = SaveWritePlanService(
        unit_of_work_factory=unit_of_work_factory, now_ms=clock.now_ms
    )
    publish_service = PublishWritePlanService(
        unit_of_work_factory=unit_of_work_factory, now_ms=clock.now_ms
    )
    save_response = save_service(
        SaveWritePlanCommand(
            command_id=f"save-{action_id}",
            request_hash="a1" * 32,
            plan_id=plan_id,
            run_id="run-1",
            revision_no=1,
            summary_text="create one task",
            expected_run_version=0,
            actions=(
                WriteActionDraft(
                    action_id=action_id,
                    connector_id=GOOGLE_WORKSPACE_CONNECTOR_ID,
                    position=1,
                    tool_name="tasks_create_task",
                    arguments={"task_list_id": "task-list-default", "payload": dict(_TASK_PAYLOAD)},
                    expected={
                        "resource_type": "task",
                        "resource_id": None,
                        "payload": dict(_TASK_PAYLOAD),
                    },
                    evidence_ids=(f"evidence-{action_id}",),
                ),
            ),
            evidence=(
                WriteEvidenceDraft(
                    evidence_id=f"evidence-{action_id}",
                    origin_type=EvidenceOriginType.DERIVED,
                    kind="USER_REQUEST",
                    excerpt="Create a follow-up task.",
                ),
            ),
        )
    )
    assert save_response.applied is True

    publish_response = publish_service(
        PublishWritePlanCommand(
            command_id=f"publish-{action_id}",
            request_hash="a2" * 32,
            plan_id=plan_id,
            run_id="run-1",
            expected_run_version=0,
        )
    )
    assert publish_response.applied is True


def test_proposed_action_modify_applies_patch_and_updates_hash(modify_database: Path) -> None:
    clock = FakeClockPort(initial_ms=1_000)
    unit_of_work_factory = sqlite_unit_of_work_factory(modify_database)
    _save_and_publish_task_action(
        database_path=modify_database, clock=clock, action_id="action-1", plan_id="plan-1"
    )
    modify_service = ModifyWriteActionService(
        unit_of_work_factory=unit_of_work_factory,
        now_ms=clock.now_ms,
        gateway=_EMPTY_TASK_LIST_GATEWAY,
    )

    result = modify_service(
        ModifyWriteActionCommand(
            command_id="modify-1",
            request_hash="b1" * 32,
            action_id="action-1",
            expected_version=0,
            arguments_patch={"title": "Send updated summary"},
        )
    )

    assert result["applied"] is True
    assert result["result_code"] == ResultCode.TRANSITION_APPLIED.value
    assert result["action_status"] == "MODIFIED"
    assert result["action_version"] == 1
    next_allowed_commands = result["next_allowed_commands"]
    assert isinstance(next_allowed_commands, tuple)
    assert "APPROVE_ACTION" not in next_allowed_commands

    with unit_of_work_factory() as unit_of_work:
        action = unit_of_work.actions.get_by_id("action-1")
    assert action is not None
    expected_arguments = {
        "task_list_id": "task-list-default",
        "payload": {"title": "Send updated summary", "notes": "draft notes"},
    }
    assert action.arguments_json == canonicalize_json_value(expected_arguments)
    assert action.arguments_hash == calculate_canonical_json_hash(expected_arguments)

    with unit_of_work_factory() as unit_of_work:
        plan = unit_of_work.plans.get_by_id("plan-1")
    assert plan is not None
    assert plan.review_status is PlanReviewStatus.REQUIRED
    assert plan.review_version == 1


def test_modify_blocks_approval_until_current_review_generation_passes(
    modify_database: Path,
) -> None:
    clock = FakeClockPort(initial_ms=1_000)
    unit_of_work_factory = sqlite_unit_of_work_factory(modify_database)
    _save_and_publish_task_action(
        database_path=modify_database, clock=clock, action_id="action-1", plan_id="plan-1"
    )
    modified = ModifyWriteActionService(
        unit_of_work_factory=unit_of_work_factory,
        now_ms=clock.now_ms,
        gateway=_EMPTY_TASK_LIST_GATEWAY,
    )(
        ModifyWriteActionCommand(
            command_id="modify-review-gate",
            request_hash="c1" * 32,
            action_id="action-1",
            expected_version=0,
            arguments_patch={"title": "Reviewed title"},
        )
    )
    assert modified["applied"] is True

    approve_service = ApproveWriteActionService(
        unit_of_work_factory=unit_of_work_factory, now_ms=clock.now_ms
    )
    blocked = approve_service(
        ApproveWriteActionCommand(
            command_id="approve-before-review",
            request_hash="c2" * 32,
            action_id="action-1",
            expected_version=1,
            approved_by_account_id="account-1",
            approved_by_display="User",
            source_snapshot={},
            approval_id="approval-before-review",
            idempotency_key="c3" * 32,
        )
    )
    assert blocked.applied is False
    assert blocked.conflict_detail == ("plan review must pass after the latest action modification")

    with unit_of_work_factory() as unit_of_work:
        assert unit_of_work.plans.update_review_if_version_and_status(
            "plan-1",
            expected_review_version=1,
            expected_review_statuses=frozenset(PlanReviewStatus),
            values={
                "review_status": PlanReviewStatus.PASSED,
                "review_disposition": "PASS",
            },
        ) is not None
        unit_of_work.commit()

    approved = approve_service(
        ApproveWriteActionCommand(
            command_id="approve-after-review",
            request_hash="c4" * 32,
            action_id="action-1",
            expected_version=1,
            approved_by_account_id="account-1",
            approved_by_display="User",
            source_snapshot={},
            approval_id="approval-after-review",
            idempotency_key="c5" * 32,
        )
    )
    assert approved.applied is True


def test_second_modify_rejects_first_generation_review_result(modify_database: Path) -> None:
    clock = FakeClockPort(initial_ms=1_000)
    unit_of_work_factory = sqlite_unit_of_work_factory(modify_database)
    _save_and_publish_task_action(
        database_path=modify_database, clock=clock, action_id="action-1", plan_id="plan-1"
    )
    modify_service = ModifyWriteActionService(
        unit_of_work_factory=unit_of_work_factory,
        now_ms=clock.now_ms,
        gateway=_EMPTY_TASK_LIST_GATEWAY,
    )
    first = modify_service(
        ModifyWriteActionCommand(
            command_id="modify-generation-1",
            request_hash="d1" * 32,
            action_id="action-1",
            expected_version=0,
            arguments_patch={"title": "First edit"},
        )
    )
    second = modify_service(
        ModifyWriteActionCommand(
            command_id="modify-generation-2",
            request_hash="d2" * 32,
            action_id="action-1",
            expected_version=1,
            arguments_patch={"title": "Second edit"},
        )
    )
    assert first["applied"] is True
    assert second["applied"] is True

    with unit_of_work_factory() as unit_of_work:
        stale_applied = unit_of_work.plans.update_review_if_version_and_status(
            "plan-1",
            expected_review_version=1,
            expected_review_statuses=frozenset(PlanReviewStatus),
            values={
                "review_status": PlanReviewStatus.PASSED,
                "review_disposition": "PASS",
            },
        )
        plan = unit_of_work.plans.get_by_id("plan-1")
    assert stale_applied is None
    assert plan is not None
    assert plan.review_status is PlanReviewStatus.REQUIRED
    assert plan.review_version == 2


def test_approved_action_modify_revokes_active_approval(modify_database: Path) -> None:
    clock = FakeClockPort(initial_ms=1_000)
    unit_of_work_factory = sqlite_unit_of_work_factory(modify_database)
    _save_and_publish_task_action(
        database_path=modify_database, clock=clock, action_id="action-1", plan_id="plan-1"
    )
    approve_service = ApproveWriteActionService(
        unit_of_work_factory=unit_of_work_factory, now_ms=clock.now_ms
    )
    modify_service = ModifyWriteActionService(
        unit_of_work_factory=unit_of_work_factory,
        now_ms=clock.now_ms,
        gateway=_EMPTY_TASK_LIST_GATEWAY,
    )
    claim_service = ClaimWriteActionService(
        unit_of_work_factory=unit_of_work_factory,
        now_ms=clock.now_ms,
        signing_secret="modify-test-secret",
        service_instance_id="modify-svc-1",
    )

    approve_response = approve_service(
        ApproveWriteActionCommand(
            command_id="approve-1",
            request_hash="a4" * 32,
            action_id="action-1",
            expected_version=0,
            approved_by_account_id="account-1",
            approved_by_display="User",
            source_snapshot={},
            approval_id="approval-1",
            idempotency_key="b1" * 32,
        )
    )
    assert approve_response.applied is True
    assert approve_response.action_status == "APPROVED"

    result = modify_service(
        ModifyWriteActionCommand(
            command_id="modify-1",
            request_hash="b1" * 32,
            action_id="action-1",
            expected_version=1,
            arguments_patch={"title": "Send updated summary"},
        )
    )
    assert result["applied"] is True
    assert result["action_status"] == "MODIFIED"

    with unit_of_work_factory() as unit_of_work:
        stale_approval = unit_of_work.approvals.get_by_id("approval-1")
        active_approval = unit_of_work.approvals.get_active_by_action("action-1")
    assert stale_approval is not None
    assert stale_approval.status is ApprovalStatus.REVOKED
    assert active_approval is None

    # The stale (revoked) approval must never authorize a claim of the
    # modified arguments.
    blocked_claim = claim_service(
        ClaimWriteActionCommand(
            command_id="claim-stale-1",
            request_hash="c1" * 32,
            action_id="action-1",
            expected_version=2,
            source_snapshot={},
            attempt_id="attempt-1",
            nonce="nonce-1",
        )
    )
    assert blocked_claim.applied is False
    assert blocked_claim.result_code == ResultCode.STATE_CONFLICT.value


class _ModifyDuplicateGateway:
    def __init__(
        self,
        *,
        database_path: Path,
        tasks: tuple[ResourceSnapshot, ...] = (),
        error: Exception | None = None,
    ) -> None:
        self.database_path = database_path
        self.tasks = tasks
        self.error = error
        self.calls = 0

    def list_tasks(
        self,
        *,
        task_list_id: str,
        page_token: str | None,
        page_size: int,
    ) -> ResourcePage:
        del task_list_id, page_token, page_size
        connection = connect_sqlite(self.database_path)
        try:
            connection.execute("BEGIN IMMEDIATE;")
            connection.execute("ROLLBACK;")
        finally:
            connection.close()
        self.calls += 1
        if self.error is not None:
            raise self.error
        return ResourcePage(items=self.tasks, next_page_token=None)


def _existing_task(resource_id: str, *, title: str, due: str | None = None) -> ResourceSnapshot:
    payload: dict[str, object] = {"title": title, "status": "needsAction"}
    if due is not None:
        payload["due"] = due
    return ResourceSnapshot(
        fixture_snapshot_id=resource_id,
        resource_type=ResourceType.TASK,
        resource_id=resource_id,
        parent_id="task-list-default",
        related_resource_ids=("task-list-default",),
        version="1",
        recovery_fingerprint=None,
        payload=payload,
    )


def test_task_modify_rechecks_duplicates_and_persists_arguments_with_risk_atomically(
    modify_database: Path,
) -> None:
    clock = FakeClockPort(initial_ms=1_000)
    unit_of_work_factory = sqlite_unit_of_work_factory(modify_database)
    _save_and_publish_task_action(
        database_path=modify_database,
        clock=clock,
        action_id="action-fresh-modify",
        plan_id="plan-fresh-modify",
    )
    gateway = _ModifyDuplicateGateway(
        database_path=modify_database,
        tasks=(_existing_task("existing-task", title="Updated title"),),
    )

    result = ModifyWriteActionService(
        unit_of_work_factory=unit_of_work_factory,
        now_ms=clock.now_ms,
        gateway=gateway,
    )(
        ModifyWriteActionCommand(
            command_id="modify-fresh-1",
            request_hash="e1" * 32,
            action_id="action-fresh-modify",
            expected_version=0,
            arguments_patch={"title": "Updated title"},
        )
    )

    assert result["applied"] is True
    assert gateway.calls == 1
    with unit_of_work_factory() as unit_of_work:
        action = unit_of_work.actions.get_by_id("action-fresh-modify")
    assert action is not None
    assert loads(action.arguments_json)["payload"]["title"] == "Updated title"
    assert action.risk["duplicate"]["decision"] == "CLEAR_DUPLICATE"  # type: ignore[index]
    assert action.risk["duplicate"]["freshness"] == "FRESH_GOOGLE_GET"  # type: ignore[index]


def test_task_modify_source_failure_changes_no_action_or_approval(
    modify_database: Path,
) -> None:
    clock = FakeClockPort(initial_ms=1_000)
    unit_of_work_factory = sqlite_unit_of_work_factory(modify_database)
    _save_and_publish_task_action(
        database_path=modify_database,
        clock=clock,
        action_id="action-failed-modify",
        plan_id="plan-failed-modify",
    )
    approve = ApproveWriteActionService(
        unit_of_work_factory=unit_of_work_factory, now_ms=clock.now_ms
    )
    assert approve(
        ApproveWriteActionCommand(
            command_id="approve-before-failed-modify",
            request_hash="e2" * 32,
            action_id="action-failed-modify",
            expected_version=0,
            approved_by_account_id="account-1",
            approved_by_display="User",
            source_snapshot={},
            approval_id="approval-before-failed-modify",
            idempotency_key="e3" * 32,
        )
    ).applied
    gateway = _ModifyDuplicateGateway(
        database_path=modify_database,
        error=TimeoutError("tasks source unavailable"),
    )

    with pytest.raises(TimeoutError, match="source unavailable"):
        ModifyWriteActionService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=clock.now_ms,
            gateway=gateway,
        )(
            ModifyWriteActionCommand(
                command_id="modify-failed-source",
                request_hash="e4" * 32,
                action_id="action-failed-modify",
                expected_version=1,
                arguments_patch={"title": "Updated title"},
            )
        )

    with unit_of_work_factory() as unit_of_work:
        action = unit_of_work.actions.get_by_id("action-failed-modify")
        approval = unit_of_work.approvals.get_active_by_action("action-failed-modify")
        receipt = unit_of_work.command_receipts.get_by_command_id("modify-failed-source")
    assert action is not None
    assert action.status == "APPROVED" and action.version == 1
    assert loads(action.arguments_json)["payload"]["title"] == "Send summary"
    assert approval is not None
    assert receipt is None


def test_modify_rejects_a_field_the_tool_schema_does_not_allow(modify_database: Path) -> None:
    clock = FakeClockPort(initial_ms=1_000)
    unit_of_work_factory = sqlite_unit_of_work_factory(modify_database)
    _save_and_publish_task_action(
        database_path=modify_database, clock=clock, action_id="action-1", plan_id="plan-1"
    )
    modify_service = ModifyWriteActionService(
        unit_of_work_factory=unit_of_work_factory,
        now_ms=clock.now_ms,
        gateway=_EMPTY_TASK_LIST_GATEWAY,
    )

    result = modify_service(
        ModifyWriteActionCommand(
            command_id="modify-invalid-1",
            request_hash="b2" * 32,
            action_id="action-1",
            expected_version=0,
            # task_list_id is the action's target/container identity, never
            # a tool-schema-allowed patch field.
            arguments_patch={"task_list_id": "task-list-attacker"},
        )
    )

    assert result["applied"] is False
    assert result["result_code"] == ResultCode.SCHEMA_VIOLATION.value
    assert result["action_status"] == "PROPOSED"
    assert result["action_version"] == 0

    with unit_of_work_factory() as unit_of_work:
        action = unit_of_work.actions.get_by_id("action-1")
    assert action is not None
    assert action.status == "PROPOSED"
    assert action.version == 0
    unchanged_arguments = {
        "task_list_id": "task-list-default",
        "payload": dict(_TASK_PAYLOAD),
    }
    assert action.arguments_json == canonicalize_json_value(unchanged_arguments)


def test_modify_version_conflict_changes_nothing(modify_database: Path) -> None:
    clock = FakeClockPort(initial_ms=1_000)
    unit_of_work_factory = sqlite_unit_of_work_factory(modify_database)
    _save_and_publish_task_action(
        database_path=modify_database, clock=clock, action_id="action-1", plan_id="plan-1"
    )
    modify_service = ModifyWriteActionService(
        unit_of_work_factory=unit_of_work_factory,
        now_ms=clock.now_ms,
        gateway=_EMPTY_TASK_LIST_GATEWAY,
    )

    result = modify_service(
        ModifyWriteActionCommand(
            command_id="modify-conflict-1",
            request_hash="b3" * 32,
            action_id="action-1",
            expected_version=99,
            arguments_patch={"title": "Send updated summary"},
        )
    )

    assert result["applied"] is False
    assert result["result_code"] == ResultCode.VERSION_CONFLICT.value

    with unit_of_work_factory() as unit_of_work:
        action = unit_of_work.actions.get_by_id("action-1")
    assert action is not None
    assert action.status == "PROPOSED"
    assert action.version == 0


def test_modify_command_replay_returns_the_cached_result_without_reapplying(
    modify_database: Path,
) -> None:
    clock = FakeClockPort(initial_ms=1_000)
    unit_of_work_factory = sqlite_unit_of_work_factory(modify_database)
    _save_and_publish_task_action(
        database_path=modify_database, clock=clock, action_id="action-1", plan_id="plan-1"
    )
    modify_service = ModifyWriteActionService(
        unit_of_work_factory=unit_of_work_factory,
        now_ms=clock.now_ms,
        gateway=_EMPTY_TASK_LIST_GATEWAY,
    )

    command = ModifyWriteActionCommand(
        command_id="modify-replay-1",
        request_hash="b4" * 32,
        action_id="action-1",
        expected_version=0,
        arguments_patch={"title": "Send updated summary"},
    )
    first = modify_service(command)
    second = modify_service(command)
    assert first == second
    assert second["action_version"] == 1

    with unit_of_work_factory() as unit_of_work:
        action = unit_of_work.actions.get_by_id("action-1")
    assert action is not None
    assert action.version == 1

    conflicting = modify_service(
        ModifyWriteActionCommand(
            command_id="modify-replay-1",
            request_hash="b5" * 32,
            action_id="action-1",
            expected_version=1,
            arguments_patch={"title": "A different title"},
        )
    )
    assert conflicting["applied"] is False
    assert conflicting["result_code"] == ResultCode.DUPLICATE_COMMAND.value

    with unit_of_work_factory() as unit_of_work:
        action = unit_of_work.actions.get_by_id("action-1")
    assert action is not None
    assert action.version == 1


def test_modify_records_an_action_modified_audit_event(modify_database: Path) -> None:
    clock = FakeClockPort(initial_ms=1_000)
    unit_of_work_factory = sqlite_unit_of_work_factory(modify_database)
    _save_and_publish_task_action(
        database_path=modify_database, clock=clock, action_id="action-1", plan_id="plan-1"
    )
    modify_service = ModifyWriteActionService(
        unit_of_work_factory=unit_of_work_factory,
        now_ms=clock.now_ms,
        gateway=_EMPTY_TASK_LIST_GATEWAY,
    )

    result = modify_service(
        ModifyWriteActionCommand(
            command_id="modify-audit-1",
            request_hash="b6" * 32,
            action_id="action-1",
            expected_version=0,
            arguments_patch={"title": "Send updated summary"},
        )
    )
    assert result["applied"] is True

    with unit_of_work_factory() as unit_of_work:
        audit_events = unit_of_work.audits.list_by_aggregate(run_id="run-1", action_id="action-1")
    modified_events = [event for event in audit_events if event.event_type == "ACTION_MODIFIED"]
    assert len(modified_events) == 1
    assert modified_events[0].outcome == ResultCode.TRANSITION_APPLIED.value


def test_failed_action_is_not_modifiable_through_this_endpoint(modify_database: Path) -> None:
    """FAILED retries must go through prepare_write_retry, not modify_action."""

    clock = FakeClockPort(initial_ms=1_000)
    unit_of_work_factory = sqlite_unit_of_work_factory(modify_database)
    _save_and_publish_task_action(
        database_path=modify_database, clock=clock, action_id="action-1", plan_id="plan-1"
    )
    approved = ApproveWriteActionService(
        unit_of_work_factory=unit_of_work_factory, now_ms=clock.now_ms
    )(
        ApproveWriteActionCommand(
            command_id="approve-failed-modify",
            request_hash="f1" * 32,
            action_id="action-1",
            expected_version=0,
            approved_by_account_id="account-1",
            approved_by_display="User",
            source_snapshot={},
            approval_id="approval-failed-modify",
            idempotency_key="f2" * 32,
        )
    )
    assert approved.applied is True
    claimed = ClaimWriteActionService(
        unit_of_work_factory=unit_of_work_factory,
        now_ms=clock.now_ms,
        signing_secret="failed-modify-secret",
        service_instance_id="failed-modify-service",
    )(
        ClaimWriteActionCommand(
            command_id="claim-failed-modify",
            request_hash="f3" * 32,
            action_id="action-1",
            expected_version=1,
            source_snapshot={},
            attempt_id="attempt-failed-modify",
            nonce="nonce-failed-modify",
        )
    )
    assert claimed.applied is True
    with unit_of_work_factory() as unit_of_work:
        unit_of_work.execution_attempts.update_if_version_and_status(
            "attempt-failed-modify",
            expected_version=0,
            expected_status=ExecutionAttemptStatus.CLAIMED,
            status=ExecutionAttemptStatus.FAILED,
            error_code="NOT_SENT",
            error_detail_json="{}",
            result_resource_ref_id=None,
            response_metadata_json=None,
            finished_at_ms=clock.now_ms(),
        )
        unit_of_work.actions.update_if_version_and_status(
            "action-1",
            expected_version=2,
            expected_status=ActionStatus.EXECUTING,
            next_status=ActionStatus.FAILED,
            updated_at_ms=clock.now_ms(),
        )
        unit_of_work.commit()

    modify_service = ModifyWriteActionService(
        unit_of_work_factory=unit_of_work_factory,
        now_ms=clock.now_ms,
        gateway=_EMPTY_TASK_LIST_GATEWAY,
    )
    result = modify_service(
        ModifyWriteActionCommand(
            command_id="modify-failed-1",
            request_hash="b7" * 32,
            action_id="action-1",
            expected_version=3,
            arguments_patch={"title": "Should not apply"},
        )
    )

    assert result["applied"] is False
    assert result["result_code"] == ResultCode.STATE_CONFLICT.value

    with unit_of_work_factory() as unit_of_work:
        action = unit_of_work.actions.get_by_id("action-1")
    assert action is not None
    assert action.status == "FAILED"
    assert action.version == 3


def test_empty_patch_on_proposed_action_applies_nothing(modify_database: Path) -> None:
    clock = FakeClockPort(initial_ms=1_000)
    unit_of_work_factory = sqlite_unit_of_work_factory(modify_database)
    _save_and_publish_task_action(
        database_path=modify_database, clock=clock, action_id="action-1", plan_id="plan-1"
    )
    modify_service = ModifyWriteActionService(
        unit_of_work_factory=unit_of_work_factory,
        now_ms=clock.now_ms,
        gateway=_EMPTY_TASK_LIST_GATEWAY,
    )

    result = modify_service(
        ModifyWriteActionCommand(
            command_id="modify-noop-1",
            request_hash="c1" * 32,
            action_id="action-1",
            expected_version=0,
            arguments_patch={},
        )
    )

    assert result["applied"] is False
    assert result["result_code"] == ResultCode.STATE_CONFLICT.value
    assert result["action_status"] == "PROPOSED"
    assert result["action_version"] == 0

    with unit_of_work_factory() as unit_of_work:
        action = unit_of_work.actions.get_by_id("action-1")
    assert action is not None
    assert action.status == "PROPOSED"
    assert action.version == 0
    assert action.arguments_json == canonicalize_json_value(
        {"task_list_id": "task-list-default", "payload": dict(_TASK_PAYLOAD)}
    )


def test_semantically_identical_patch_on_approved_action_does_not_revoke_approval(
    modify_database: Path,
) -> None:
    clock = FakeClockPort(initial_ms=1_000)
    unit_of_work_factory = sqlite_unit_of_work_factory(modify_database)
    _save_and_publish_task_action(
        database_path=modify_database, clock=clock, action_id="action-1", plan_id="plan-1"
    )
    approve_service = ApproveWriteActionService(
        unit_of_work_factory=unit_of_work_factory, now_ms=clock.now_ms
    )
    modify_service = ModifyWriteActionService(
        unit_of_work_factory=unit_of_work_factory,
        now_ms=clock.now_ms,
        gateway=_EMPTY_TASK_LIST_GATEWAY,
    )

    approve_response = approve_service(
        ApproveWriteActionCommand(
            command_id="approve-noop-1",
            request_hash="a4" * 32,
            action_id="action-1",
            expected_version=0,
            approved_by_account_id="account-1",
            approved_by_display="User",
            source_snapshot={},
            approval_id="approval-noop-1",
            idempotency_key="b1" * 32,
        )
    )
    assert approve_response.applied is True

    # Empty patch.
    empty_result = modify_service(
        ModifyWriteActionCommand(
            command_id="modify-noop-2",
            request_hash="c2" * 32,
            action_id="action-1",
            expected_version=1,
            arguments_patch={},
        )
    )
    assert empty_result["applied"] is False
    assert empty_result["result_code"] == ResultCode.STATE_CONFLICT.value
    assert empty_result["action_status"] == "APPROVED"
    assert empty_result["action_version"] == 1

    # Patch that only restates the field's current value.
    identical_result = modify_service(
        ModifyWriteActionCommand(
            command_id="modify-noop-3",
            request_hash="c3" * 32,
            action_id="action-1",
            expected_version=1,
            arguments_patch={"title": _TASK_PAYLOAD["title"]},
        )
    )
    assert identical_result["applied"] is False
    assert identical_result["result_code"] == ResultCode.STATE_CONFLICT.value
    assert identical_result["action_status"] == "APPROVED"
    assert identical_result["action_version"] == 1

    with unit_of_work_factory() as unit_of_work:
        action = unit_of_work.actions.get_by_id("action-1")
        approval = unit_of_work.approvals.get_by_id("approval-noop-1")
        active_approval = unit_of_work.approvals.get_active_by_action("action-1")
    assert action is not None
    assert action.status == "APPROVED"
    assert action.version == 1
    assert approval is not None
    assert approval.status is ApprovalStatus.ACTIVE
    assert active_approval is not None
    assert active_approval.id == "approval-noop-1"


def test_modify_revokes_stale_approval_on_a_direct_dependent_action(
    modify_database: Path,
) -> None:
    """08-sequence-design.md/03-system-architecture.md require Modify to
    trigger dependency re-review; a full Supervisor re-plan does not exist
    yet (separate GAP), but a stale dependent must never stay claimable on
    its old Approval. The dependency edge below is saved through the real
    `SaveWritePlanService` (`WriteActionDraft.depends_on_action_ids`), not
    seeded directly, proving the safety net is reachable through the actual
    production WRITE plan path.
    """

    clock = FakeClockPort(initial_ms=1_000)
    unit_of_work_factory = sqlite_unit_of_work_factory(modify_database)
    save_service = SaveWritePlanService(
        unit_of_work_factory=unit_of_work_factory, now_ms=clock.now_ms
    )
    publish_service = PublishWritePlanService(
        unit_of_work_factory=unit_of_work_factory, now_ms=clock.now_ms
    )
    approve_service = ApproveWriteActionService(
        unit_of_work_factory=unit_of_work_factory, now_ms=clock.now_ms
    )
    modify_service = ModifyWriteActionService(
        unit_of_work_factory=unit_of_work_factory,
        now_ms=clock.now_ms,
        gateway=_EMPTY_TASK_LIST_GATEWAY,
    )
    claim_service = ClaimWriteActionService(
        unit_of_work_factory=unit_of_work_factory,
        now_ms=clock.now_ms,
        signing_secret="modify-dependency-secret",
        service_instance_id="modify-svc-dep",
    )

    def _draft(
        action_id: str, position: int, *, depends_on_action_ids: tuple[str, ...] = ()
    ) -> WriteActionDraft:
        return WriteActionDraft(
            action_id=action_id,
            connector_id=GOOGLE_WORKSPACE_CONNECTOR_ID,
            position=position,
            tool_name="tasks_create_task",
            arguments={"task_list_id": "task-list-default", "payload": dict(_TASK_PAYLOAD)},
            expected={"resource_type": "task", "resource_id": None, "payload": dict(_TASK_PAYLOAD)},
            evidence_ids=(f"evidence-{action_id}",),
            depends_on_action_ids=depends_on_action_ids,
        )

    save_response = save_service(
        SaveWritePlanCommand(
            command_id="save-dep-1",
            request_hash="d1" * 32,
            plan_id="plan-dep",
            run_id="run-1",
            revision_no=1,
            summary_text="upstream and dependent task",
            expected_run_version=0,
            actions=(
                _draft("action-upstream", 1),
                _draft("action-dependent", 2, depends_on_action_ids=("action-upstream",)),
            ),
            evidence=(
                WriteEvidenceDraft(
                    evidence_id="evidence-action-upstream",
                    origin_type=EvidenceOriginType.DERIVED,
                    kind="USER_REQUEST",
                    excerpt="Create the upstream task.",
                ),
                WriteEvidenceDraft(
                    evidence_id="evidence-action-dependent",
                    origin_type=EvidenceOriginType.DERIVED,
                    kind="USER_REQUEST",
                    excerpt="Create the dependent task.",
                ),
            ),
        )
    )
    assert save_response.applied is True

    publish_response = publish_service(
        PublishWritePlanCommand(
            command_id="publish-dep-1",
            request_hash="d2" * 32,
            plan_id="plan-dep",
            run_id="run-1",
            expected_run_version=0,
        )
    )
    assert publish_response.applied is True

    with unit_of_work_factory() as unit_of_work:
        assert unit_of_work.action_dependencies.list_dependencies("action-dependent") == (
            "action-upstream",
        )

    for action_id, approval_id in (
        ("action-upstream", "approval-upstream"),
        ("action-dependent", "approval-dependent"),
    ):
        approve_response = approve_service(
            ApproveWriteActionCommand(
                command_id=f"approve-{action_id}",
                request_hash=(f"e{action_id}" * 8)[:64],
                action_id=action_id,
                expected_version=0,
                approved_by_account_id="account-1",
                approved_by_display="User",
                source_snapshot={},
                approval_id=approval_id,
                idempotency_key=(f"f{action_id}" * 8)[:64],
            )
        )
        assert approve_response.applied is True
        assert approve_response.action_status == "APPROVED"

    modify_result = modify_service(
        ModifyWriteActionCommand(
            command_id="modify-dep-1",
            request_hash="d3" * 32,
            action_id="action-upstream",
            expected_version=1,
            arguments_patch={"due": "2026-09-01"},
        )
    )
    assert modify_result["applied"] is True
    assert modify_result["action_status"] == "MODIFIED"

    with unit_of_work_factory() as unit_of_work:
        dependent_action = unit_of_work.actions.get_by_id("action-dependent")
        dependent_active_approval = unit_of_work.approvals.get_active_by_action("action-dependent")
        dependent_stale_approval = unit_of_work.approvals.get_by_id("approval-dependent")
        dependent_audit_events = unit_of_work.audits.list_by_aggregate(
            run_id="run-1", action_id="action-dependent"
        )
    assert dependent_action is not None
    # The dependent's own status/version is untouched -- there is no Domain
    # command yet for "APPROVED, needs a fresh look, content unchanged".
    assert dependent_action.status == "APPROVED"
    assert dependent_action.version == 1
    assert dependent_active_approval is None
    assert dependent_stale_approval is not None
    assert dependent_stale_approval.status is ApprovalStatus.REVOKED
    cascade_events = [
        event
        for event in dependent_audit_events
        if event.event_type == "ACTION_DEPENDENT_APPROVAL_REVOKED"
    ]
    assert len(cascade_events) == 1

    blocked_claim = claim_service(
        ClaimWriteActionCommand(
            command_id="claim-dependent-stale-1",
            request_hash="d4" * 32,
            action_id="action-dependent",
            expected_version=1,
            source_snapshot={},
            attempt_id="attempt-dependent-1",
            nonce="nonce-dependent-1",
        )
    )
    assert blocked_claim.applied is False
    assert blocked_claim.result_code == ResultCode.STATE_CONFLICT.value
