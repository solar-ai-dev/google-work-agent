"""Reject Action audit, approval, dependency, receipt, and aggregate contract."""

from json import loads
from pathlib import Path

import pytest

from google_work_agent.adapters.persistence import (
    apply_migrations,
    connect_sqlite,
    sqlite_unit_of_work_factory,
)
from google_work_agent.application import (
    ApproveWriteActionCommand,
    ApproveWriteActionService,
    ClaimWriteActionCommand,
    ClaimWriteActionService,
    PublishWritePlanCommand,
    PublishWritePlanService,
    RejectWriteActionCommand,
    RejectWriteActionService,
    SaveWritePlanCommand,
    SaveWritePlanService,
)
from google_work_agent.domain import ApprovalStatus, ResultCode
from tests.integration.persistence.test_action_modify_vertical_slice import (
    _save_and_publish_task_action,
)
from tests.integration.persistence.test_write_action_dependency_persistence import (
    _evidence,
    _task_draft,
)
from tests.support.fakes import FakeClock


@pytest.fixture()
def modify_database(tmp_path: Path) -> Path:
    database_path = tmp_path / "reject-actions.db"
    with connect_sqlite(database_path) as connection:
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
            ) VALUES (
                'run-1', 'conversation-1', 'AGENT_SEARCH', 'PLANNING', 'thread-1',
                'AUTO', '{}', 0, 100
            );
            """
        )
    return database_path


def _service(database_path: Path, clock: FakeClock) -> RejectWriteActionService:
    return RejectWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        now_ms=clock.now_ms,
    )


def _approve(database_path: Path, clock: FakeClock, action_id: str) -> None:
    response = ApproveWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        now_ms=clock.now_ms,
    )(
        ApproveWriteActionCommand(
            command_id=f"approve-{action_id}",
            request_hash=f"approve-{action_id}".ljust(64, "0"),
            action_id=action_id,
            expected_version=0,
            approved_by_account_id="account-1",
            approved_by_display="User",
            source_snapshot={},
            approval_id=f"approval-{action_id}",
            idempotency_key=f"key-{action_id}".ljust(64, "0"),
        )
    )
    assert response.applied is True


@pytest.mark.parametrize("starting_status", ["PROPOSED", "MODIFIED", "APPROVED"])
def test_reject_allowed_statuses_record_audit_and_finalize_terminal_plan(
    modify_database: Path, starting_status: str
) -> None:
    clock = FakeClock(initial_ms=1_000)
    _save_and_publish_task_action(
        database_path=modify_database,
        clock=clock,
        action_id="action-1",
        plan_id="plan-1",
    )
    expected_version = 0
    if starting_status == "MODIFIED":
        with connect_sqlite(modify_database) as connection:
            connection.execute("UPDATE actions SET status = 'MODIFIED' WHERE id = 'action-1';")
    elif starting_status == "APPROVED":
        _approve(modify_database, clock, "action-1")
        expected_version = 1

    result = _service(modify_database, clock)(
        RejectWriteActionCommand(
            command_id=f"reject-{starting_status.lower()}",
            request_hash=f"reject-{starting_status}".ljust(64, "0"),
            action_id="action-1",
            expected_version=expected_version,
            actor_account_id="account-1",
            reason_code="USER_DECLINED",
        )
    )

    assert result["applied"] is True
    assert result["action_status"] == "REJECTED"
    with sqlite_unit_of_work_factory(modify_database)() as unit_of_work:
        action = unit_of_work.actions.get_by_id("action-1")
        plan = unit_of_work.plans.get_by_id("plan-1")
        run = unit_of_work.runs.get_by_id("run-1")
        approvals = unit_of_work.approvals.list_by_action("action-1")
        attempts = tuple(
            attempt
            for approval in approvals
            for attempt in unit_of_work.execution_attempts.list_by_approval(approval.id)
        )
        audits = unit_of_work.audits.list_by_aggregate(run_id="run-1", cursor_after=None, limit=100)
    assert action is not None and action.status == "REJECTED"
    assert plan is not None and plan.status.value == "COMPLETED"
    assert run is not None and run.status.value == "COMPLETED"
    assert attempts == ()
    if approvals:
        assert approvals[-1].status is ApprovalStatus.REVOKED
    rejected = [event for event in audits if event.event_type == "ACTION_REJECTED"]
    assert len(rejected) == 1
    metadata = loads(rejected[0].metadata_json)["attributes"]
    assert metadata["plan_id"] == "plan-1"
    assert metadata["previous_status"] == starting_status
    assert metadata["new_status"] == "REJECTED"
    assert metadata["reason_code"] == "USER_DECLINED"
    assert metadata["reason_present"] is True
    assert "Send summary" not in rejected[0].metadata_json
    assert rejected[0].actor_type == "USER"
    assert rejected[0].actor_id == "account-1"
    assert rejected[0].outcome == ResultCode.TRANSITION_APPLIED.value


def test_reject_keeps_plan_and_run_active_when_independent_action_is_pending(
    modify_database: Path,
) -> None:
    clock = FakeClock(initial_ms=1_000)
    factory = sqlite_unit_of_work_factory(modify_database)
    assert SaveWritePlanService(unit_of_work_factory=factory, now_ms=clock.now_ms)(
        SaveWritePlanCommand(
            command_id="save-independent-reject",
            request_hash="7" * 64,
            plan_id="plan-independent",
            run_id="run-1",
            revision_no=1,
            summary_text="independent actions",
            expected_run_version=0,
            actions=(
                _task_draft("action-a", 1),
                _task_draft("action-b", 2),
            ),
            evidence=_evidence("action-a", "action-b"),
        )
    ).applied
    assert PublishWritePlanService(unit_of_work_factory=factory, now_ms=clock.now_ms)(
        PublishWritePlanCommand(
            command_id="publish-independent-reject",
            request_hash="8" * 64,
            plan_id="plan-independent",
            run_id="run-1",
            expected_run_version=0,
        )
    ).applied

    result = _service(modify_database, clock)(
        RejectWriteActionCommand(
            command_id="reject-independent-a",
            request_hash="9" * 64,
            action_id="action-a",
            expected_version=0,
        )
    )

    assert result["applied"] is True
    with factory() as unit_of_work:
        action_a = unit_of_work.actions.get_by_id("action-a")
        action_b = unit_of_work.actions.get_by_id("action-b")
        plan = unit_of_work.plans.get_by_id("plan-independent")
        run = unit_of_work.runs.get_by_id("run-1")
    assert action_a is not None and action_a.status == "REJECTED"
    assert action_b is not None and action_b.status == "PROPOSED"
    assert plan is not None and plan.status.value == "WAITING_APPROVAL"
    assert run is not None and run.status.value == "WAITING_APPROVAL"


@pytest.mark.parametrize(
    "status",
    ["REJECTED", "EXECUTING", "EXECUTED", "VERIFIED", "MISMATCH", "UNKNOWN_RESULT"],
)
def test_reject_forbidden_statuses_mutate_nothing(modify_database: Path, status: str) -> None:
    clock = FakeClock(initial_ms=1_000)
    _save_and_publish_task_action(
        database_path=modify_database,
        clock=clock,
        action_id="action-1",
        plan_id="plan-1",
    )
    with connect_sqlite(modify_database) as connection:
        connection.execute("UPDATE actions SET status = ? WHERE id = 'action-1';", (status,))

    result = _service(modify_database, clock)(
        RejectWriteActionCommand(
            command_id=f"reject-forbidden-{status}",
            request_hash=f"forbidden-{status}".ljust(64, "0"),
            action_id="action-1",
            expected_version=0,
        )
    )

    assert result["applied"] is False
    assert result["result_code"] == ResultCode.STATE_CONFLICT.value
    with sqlite_unit_of_work_factory(modify_database)() as unit_of_work:
        action = unit_of_work.actions.get_by_id("action-1")
        audits = unit_of_work.audits.list_by_aggregate(run_id="run-1", cursor_after=None, limit=100)
    assert action is not None and action.status == status and action.version == 0
    assert [event for event in audits if event.event_type == "ACTION_REJECTED"] == []


def test_reject_receipt_replay_hash_and_version_contract(modify_database: Path) -> None:
    clock = FakeClock(initial_ms=1_000)
    _save_and_publish_task_action(
        database_path=modify_database,
        clock=clock,
        action_id="action-1",
        plan_id="plan-1",
    )
    service = _service(modify_database, clock)
    command = RejectWriteActionCommand(
        command_id="reject-replay",
        request_hash="a" * 64,
        action_id="action-1",
        expected_version=0,
    )
    first = service(command)
    replay = service(command)
    mismatch = service(
        RejectWriteActionCommand(
            command_id="reject-replay",
            request_hash="b" * 64,
            action_id="action-1",
            expected_version=0,
        )
    )
    stale = service(
        RejectWriteActionCommand(
            command_id="reject-stale",
            request_hash="c" * 64,
            action_id="action-1",
            expected_version=0,
        )
    )

    assert replay == first
    assert mismatch["result_code"] == ResultCode.DUPLICATE_COMMAND.value
    assert stale["result_code"] == ResultCode.VERSION_CONFLICT.value
    with sqlite_unit_of_work_factory(modify_database)() as unit_of_work:
        action = unit_of_work.actions.get_by_id("action-1")
        audits = unit_of_work.audits.list_by_aggregate(run_id="run-1", cursor_after=None, limit=100)
    assert action is not None and action.version == 1
    assert len([event for event in audits if event.event_type == "ACTION_REJECTED"]) == 1


@pytest.mark.parametrize("reason_code", ["", "free text", "BAD\nVALUE", "A" * 129])
def test_reject_rejects_unsafe_reason_codes_before_receipt(
    modify_database: Path, reason_code: str
) -> None:
    clock = FakeClock(initial_ms=1_000)
    _save_and_publish_task_action(
        database_path=modify_database,
        clock=clock,
        action_id="action-1",
        plan_id="plan-1",
    )
    with pytest.raises(ValueError, match="safe uppercase identifier"):
        _service(modify_database, clock)(
            RejectWriteActionCommand(
                command_id="reject-invalid-reason",
                request_hash="6" * 64,
                action_id="action-1",
                expected_version=0,
                reason_code=reason_code,
            )
        )
    with sqlite_unit_of_work_factory(modify_database)() as unit_of_work:
        action = unit_of_work.actions.get_by_id("action-1")
        receipt = unit_of_work.command_receipts.get_by_command_id("reject-invalid-reason")
    assert action is not None and action.status == "PROPOSED"
    assert receipt is None


def test_reject_blocks_proposed_direct_dependent_before_claim(
    modify_database: Path,
) -> None:
    clock = FakeClock(initial_ms=1_000)
    factory = sqlite_unit_of_work_factory(modify_database)
    assert SaveWritePlanService(unit_of_work_factory=factory, now_ms=clock.now_ms)(
        SaveWritePlanCommand(
            command_id="save-proposed-dependency",
            request_hash="a" * 64,
            plan_id="plan-proposed-dependency",
            run_id="run-1",
            revision_no=1,
            summary_text="proposed dependency",
            expected_run_version=0,
            actions=(
                _task_draft("action-a", 1),
                _task_draft("action-b", 2, depends_on_action_ids=("action-a",)),
            ),
            evidence=_evidence("action-a", "action-b"),
        )
    ).applied
    assert PublishWritePlanService(unit_of_work_factory=factory, now_ms=clock.now_ms)(
        PublishWritePlanCommand(
            command_id="publish-proposed-dependency",
            request_hash="b" * 64,
            plan_id="plan-proposed-dependency",
            run_id="run-1",
            expected_run_version=0,
        )
    ).applied

    assert _service(modify_database, clock)(
        RejectWriteActionCommand(
            command_id="reject-proposed-dependency",
            request_hash="c" * 64,
            action_id="action-a",
            expected_version=0,
        )
    )["applied"]
    claim = ClaimWriteActionService(
        unit_of_work_factory=factory,
        now_ms=clock.now_ms,
        signing_secret="reject-secret",
        service_instance_id="reject-service",
    )(
        ClaimWriteActionCommand(
            command_id="claim-proposed-dependent",
            request_hash="d" * 64,
            action_id="action-b",
            expected_version=1,
            source_snapshot={},
            attempt_id="attempt-proposed-b",
            nonce="claim-proposed-b",
        )
    )

    assert claim.applied is False
    assert claim.attempt_id is None
    with factory() as unit_of_work:
        dependent = unit_of_work.actions.get_by_id("action-b")
    with connect_sqlite(modify_database) as connection:
        attempt_count = connection.execute("SELECT COUNT(*) FROM execution_attempts;").fetchone()[0]
    assert dependent is not None and dependent.status == "DEPENDENCY_BLOCKED"
    assert attempt_count == 0


def test_reject_blocks_and_revokes_transitive_pending_dependents(
    modify_database: Path,
) -> None:
    clock = FakeClock(initial_ms=1_000)
    factory = sqlite_unit_of_work_factory(modify_database)
    saved = SaveWritePlanService(unit_of_work_factory=factory, now_ms=clock.now_ms)(
        SaveWritePlanCommand(
            command_id="save-reject-chain",
            request_hash="d" * 64,
            plan_id="plan-chain",
            run_id="run-1",
            revision_no=1,
            summary_text="A -> B -> C",
            expected_run_version=0,
            actions=(
                _task_draft("action-a", 1),
                _task_draft("action-b", 2, depends_on_action_ids=("action-a",)),
                _task_draft("action-c", 3, depends_on_action_ids=("action-b",)),
            ),
            evidence=_evidence("action-a", "action-b", "action-c"),
        )
    )
    assert saved.applied is True
    assert PublishWritePlanService(unit_of_work_factory=factory, now_ms=clock.now_ms)(
        PublishWritePlanCommand(
            command_id="publish-reject-chain",
            request_hash="e" * 64,
            plan_id="plan-chain",
            run_id="run-1",
            expected_run_version=0,
        )
    ).applied
    for action_id in ("action-a", "action-b", "action-c"):
        _approve(modify_database, clock, action_id)

    rejected = _service(modify_database, clock)(
        RejectWriteActionCommand(
            command_id="reject-chain",
            request_hash="f" * 64,
            action_id="action-a",
            expected_version=1,
        )
    )
    assert rejected["applied"] is True

    with factory() as unit_of_work:
        actions = {item.id: item for item in unit_of_work.actions.list_by_plan("plan-chain")}
        approvals = {
            action_id: unit_of_work.approvals.list_by_action(action_id)[-1] for action_id in actions
        }
        audits = unit_of_work.audits.list_by_aggregate(run_id="run-1", cursor_after=None, limit=100)
    assert actions["action-a"].status == "REJECTED"
    assert actions["action-b"].status == "DEPENDENCY_BLOCKED"
    assert actions["action-c"].status == "DEPENDENCY_BLOCKED"
    assert all(item.status is ApprovalStatus.REVOKED for item in approvals.values())
    assert {
        event.action_id for event in audits if event.event_type == "ACTION_DEPENDENCY_BLOCKED"
    } == {"action-b", "action-c"}

    claim = ClaimWriteActionService(
        unit_of_work_factory=factory,
        now_ms=clock.now_ms,
        signing_secret="reject-secret",
        service_instance_id="reject-service",
    )(
        ClaimWriteActionCommand(
            command_id="claim-rejected-dependent",
            request_hash="1" * 64,
            action_id="action-b",
            expected_version=2,
            source_snapshot={},
            attempt_id="attempt-b",
            nonce="claim-b",
        )
    )
    assert claim.applied is False
    assert claim.attempt_id is None


@pytest.mark.parametrize(
    ("rejected_action_id", "preserved_action_id"),
    [("action-a", "action-b"), ("action-b", "action-a")],
)
def test_reject_preserves_verified_actions(
    modify_database: Path,
    rejected_action_id: str,
    preserved_action_id: str,
) -> None:
    clock = FakeClock(initial_ms=1_000)
    factory = sqlite_unit_of_work_factory(modify_database)
    assert SaveWritePlanService(unit_of_work_factory=factory, now_ms=clock.now_ms)(
        SaveWritePlanCommand(
            command_id=f"save-preserve-{rejected_action_id}",
            request_hash="3" * 64,
            plan_id="plan-preserve",
            run_id="run-1",
            revision_no=1,
            summary_text="preserve verified fact",
            expected_run_version=0,
            actions=(
                _task_draft("action-a", 1),
                _task_draft("action-b", 2, depends_on_action_ids=("action-a",)),
            ),
            evidence=_evidence("action-a", "action-b"),
        )
    ).applied
    assert PublishWritePlanService(unit_of_work_factory=factory, now_ms=clock.now_ms)(
        PublishWritePlanCommand(
            command_id=f"publish-preserve-{rejected_action_id}",
            request_hash="4" * 64,
            plan_id="plan-preserve",
            run_id="run-1",
            expected_run_version=0,
        )
    ).applied
    with connect_sqlite(modify_database) as connection:
        connection.execute(
            "UPDATE actions SET status = 'VERIFIED' WHERE id = ?;",
            (preserved_action_id,),
        )

    result = _service(modify_database, clock)(
        RejectWriteActionCommand(
            command_id=f"reject-preserve-{rejected_action_id}",
            request_hash="5" * 64,
            action_id=rejected_action_id,
            expected_version=0,
        )
    )

    assert result["applied"] is True
    with factory() as unit_of_work:
        preserved = unit_of_work.actions.get_by_id(preserved_action_id)
    assert preserved is not None and preserved.status == "VERIFIED" and preserved.version == 0


def test_reject_audit_failure_rolls_back_domain_mutation(modify_database: Path) -> None:
    clock = FakeClock(initial_ms=1_000)
    _save_and_publish_task_action(
        database_path=modify_database,
        clock=clock,
        action_id="action-1",
        plan_id="plan-1",
    )
    with connect_sqlite(modify_database) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_audit_failure
            BEFORE INSERT ON audit_events
            WHEN NEW.event_type = 'ACTION_REJECTED'
            BEGIN
                SELECT RAISE(ABORT, 'reject audit failure');
            END;
            """
        )

    with pytest.raises(Exception, match="reject audit failure"):
        _service(modify_database, clock)(
            RejectWriteActionCommand(
                command_id="reject-audit-failure",
                request_hash="2" * 64,
                action_id="action-1",
                expected_version=0,
            )
        )

    with sqlite_unit_of_work_factory(modify_database)() as unit_of_work:
        action = unit_of_work.actions.get_by_id("action-1")
        receipt = unit_of_work.command_receipts.get_by_command_id("reject-audit-failure")
    assert action is not None and action.status == "PROPOSED" and action.version == 0
    assert receipt is None
