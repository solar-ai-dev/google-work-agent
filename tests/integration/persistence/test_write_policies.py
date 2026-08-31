"""Duplicate and feasibility policy integration tests."""

# ruff: noqa: F401

from __future__ import annotations

from google_work_agent.adapters.langgraph.main.routing.route_after_supervisor import (
    RESUME_CONTRACT_VERSION,
)
from google_work_agent.adapters.langgraph.registry.node_registry import NodeRegistry
from google_work_agent.adapters.langgraph.registry.resume_target_registry import (
    ResumeTargetRegistry,
)
from google_work_agent.application.use_cases.action.refresh_expired_action import (
    RefreshExpiredActionHandler,
)
from google_work_agent.application.use_cases.approval.expire_approval import (
    ExpireApprovalCommand,
    ExpireApprovalHandler,
)
from google_work_agent.application.use_cases.run.block_run import BlockRunHandler
from google_work_agent.ports.persistence.approval_repository import active_approval_tuple
from google_work_agent.ports.persistence.audit_event_repository import AuditEventCursor
from tests.integration.persistence.test_action_reject_vertical_slice import (
    _service as _seed_workflow_checkpoint,
)
from tests.integration.persistence.test_write_actions import (
    ApproveWriteActionCommand,
    ApproveWriteActionService,
    CalendarWorkHours,
    ClaimWriteActionCommand,
    ClaimWriteActionService,
    FakeClockPort,
    Path,
    PolicyViolationError,
    PreflightWriteActionService,
    ResourceSnapshot,
    ResourceType,
    _approve_preflight_action,
    _duplicate_risk,
    _duplicate_task,
    _feasibility_risk,
    _FeasibilityPreflightGateway,
    _prepare_calendar_feasibility_action,
    _prepare_write_plan,
    _TaskDuplicatePreflightGateway,
    connect_sqlite,
    loads,
    pytest,
    sqlite_unit_of_work_factory,
)
from tests.support.checkpoint import sqlite_checkpoint
from tests.support.fakes import DeterministicUUID

pytest_plugins = ("tests.integration.persistence.test_write_actions",)


def _stale_lifecycle_dependencies(database_path: Path, clock: FakeClockPort) -> dict[str, object]:
    _seed_workflow_checkpoint(database_path, clock)
    registry = ResumeTargetRegistry(
        node_registry=NodeRegistry(graph_version=RESUME_CONTRACT_VERSION),
        graph_version=RESUME_CONTRACT_VERSION,
    )
    factory = sqlite_unit_of_work_factory(database_path)
    return {
        "expire_approval": ExpireApprovalHandler(
            unit_of_work_factory=factory,
            now_ms=clock.now_ms,
        ),
        "refresh_expired_action": RefreshExpiredActionHandler(
            unit_of_work_factory=factory,
            checkpoint_port=sqlite_checkpoint(database_path),
            now_ms=clock.now_ms,
            id_factory=DeterministicUUID(prefix="preflight-review").new_uuid,
            resume_target_registry=registry,
            schedule_run_execution=None,
        ),
        "block_run": BlockRunHandler(
            unit_of_work_factory=factory,
            now_ms=clock.now_ms,
        ),
    }


def test_still_current_active_approval_cannot_be_expired(write_database: Path) -> None:
    clock = FakeClockPort(1000)
    suffix = "still-current-expiry"
    _approve_preflight_action(
        write_database=write_database,
        clock=clock,
        suffix=suffix,
        risk=_duplicate_risk("NOT_DUPLICATE"),
    )
    factory = sqlite_unit_of_work_factory(write_database)
    with factory() as unit_of_work:
        approval = unit_of_work.approvals.get_active_for_action(f"action-{suffix}")
    assert approval is not None

    with pytest.raises(ValueError, match="still-current"):
        ExpireApprovalHandler(unit_of_work_factory=factory, now_ms=clock.now_ms)(
            ExpireApprovalCommand(
                command_id="expire-still-current",
                request_hash="ab" * 32,
                approval_id=approval.id,
                expected_action_version=approval.action_version,
                current_source_snapshot=loads(approval.source_snapshot_json),
            )
        )

    with factory() as unit_of_work:
        current = unit_of_work.approvals.get_active_for_action(f"action-{suffix}")
        action = unit_of_work.actions.get(f"action-{suffix}")
        receipt = unit_of_work.command_receipts.get_by_command_id("expire-still-current")
    assert current is not None and current.status.value == "ACTIVE"
    assert action is not None and action.status == "APPROVED"
    assert receipt is None


@pytest.mark.parametrize(
    ("decision", "acknowledged", "expected_applied"),
    [
        ("NOT_DUPLICATE", False, True),
        ("SIMILAR_CANDIDATE", False, False),
        ("SIMILAR_CANDIDATE", True, True),
        ("CLEAR_DUPLICATE", False, False),
        ("CLEAR_DUPLICATE", True, True),
    ],
)
def test_task_duplicate_approval_matrix(
    write_database: Path,
    decision: str,
    acknowledged: bool,
    expected_applied: bool,
) -> None:
    clock = FakeClockPort(1000)
    matched_ids = () if decision == "NOT_DUPLICATE" else ("existing-task",)
    _prepare_write_plan(
        write_database=write_database,
        clock=clock,
        suffix="dup-approval",
        risk=_duplicate_risk(decision, matched_ids=matched_ids),
    )
    service = ApproveWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )

    response = service(
        ApproveWriteActionCommand(
            command_id="approve-duplicate",
            request_hash="fa" * 32,
            action_id="action-dup-approval",
            expected_version=0,
            approved_by_account_id="account-1",
            approved_by_display="User",
            source_snapshot={},
            approval_id="approval-duplicate",
            idempotency_key="fb" * 32,
            duplicate_acknowledged=acknowledged,
        )
    )

    assert response.applied is expected_applied
    with sqlite_unit_of_work_factory(write_database)() as unit_of_work:
        approvals = active_approval_tuple(unit_of_work.approvals, "action-dup-approval")
    assert len(approvals) == int(expected_applied)
    if approvals:
        snapshot = loads(approvals[0].source_snapshot_json)
        assert snapshot["task_duplicate"]["risk"]["matched_resource_ids"] == list(matched_ids)
        assert "client-forged" not in approvals[0].source_snapshot_json


def test_task_duplicate_approval_replay_does_not_duplicate_override_audit(
    write_database: Path,
) -> None:
    clock = FakeClockPort(1000)
    _prepare_write_plan(
        write_database=write_database,
        clock=clock,
        suffix="dup-replay",
        risk=_duplicate_risk("CLEAR_DUPLICATE", matched_ids=("existing-task",)),
    )
    service = ApproveWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )
    command = ApproveWriteActionCommand(
        command_id="approve-duplicate-replay",
        request_hash="fc" * 32,
        action_id="action-dup-replay",
        expected_version=0,
        approved_by_account_id="account-1",
        approved_by_display="User",
        source_snapshot={},
        approval_id="approval-duplicate-replay",
        idempotency_key="fd" * 32,
        duplicate_acknowledged=True,
    )

    assert service(command) == service(command)
    with sqlite_unit_of_work_factory(write_database)() as unit_of_work:
        events = unit_of_work.audits.list_page(
            AuditEventCursor(run_id="run-1", action_id="action-dup-replay"), 100
        )
    assert sum(event.event_type == "TASK_DUPLICATE_OVERRIDE_ACKNOWLEDGED" for event in events) == 1


def test_task_duplicate_preflight_new_match_revokes_stale_approval(
    write_database: Path,
) -> None:
    clock = FakeClockPort(1000)
    suffix = "fresh-new"
    _approve_preflight_action(
        write_database=write_database,
        clock=clock,
        suffix=suffix,
        risk=_duplicate_risk("NOT_DUPLICATE"),
    )
    gateway = _TaskDuplicatePreflightGateway(
        database_path=write_database,
        tasks=(_duplicate_task("new-task", title=f"title-{suffix}"),),
    )

    with pytest.raises(PolicyViolationError, match="reapproval"):
        PreflightWriteActionService(
            unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
            gateway=gateway,  # type: ignore[arg-type]
            now_ms=clock.now_ms,
            **_stale_lifecycle_dependencies(write_database, clock),  # type: ignore[arg-type]
        )(action_id=f"action-{suffix}")

    with sqlite_unit_of_work_factory(write_database)() as unit_of_work:
        action = unit_of_work.actions.get(f"action-{suffix}")
        approval = unit_of_work.approvals.get_active_for_action(f"action-{suffix}")
        expired_approval = unit_of_work.approvals.get(f"approval-{suffix}")
    assert action is not None
    assert action.status == "MODIFIED"
    assert action.version == 3
    assert action.risk["duplicate"]["freshness"] == "FRESH_GOOGLE_GET"  # type: ignore[index]
    assert approval is None
    assert expired_approval is not None and expired_approval.status.value == "EXPIRED"
    with connect_sqlite(write_database) as connection:
        handoff = connection.execute(
            """SELECT status, resume_target_json FROM workflow_handoffs
               WHERE trigger_command_id=?;""",
            (f"system:preflight-refresh:approval-{suffix}",),
        ).fetchone()
    assert handoff is not None and handoff["status"] == "PENDING"
    assert loads(handoff["resume_target_json"])["stage_id"] == "REVIEW_ENTRY"


def test_task_duplicate_preflight_same_acknowledged_match_allows_claim(
    write_database: Path,
) -> None:
    clock = FakeClockPort(1000)
    suffix = "fresh-same"
    risk = _duplicate_risk("CLEAR_DUPLICATE", matched_ids=("existing-task",))
    _approve_preflight_action(
        write_database=write_database,
        clock=clock,
        suffix=suffix,
        risk=risk,
    )
    gateway = _TaskDuplicatePreflightGateway(
        database_path=write_database,
        tasks=(_duplicate_task("existing-task", title=f"title-{suffix}"),),
    )

    PreflightWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        gateway=gateway,  # type: ignore[arg-type]
        now_ms=clock.now_ms,
    )(action_id=f"action-{suffix}")

    with sqlite_unit_of_work_factory(write_database)() as unit_of_work:
        action = unit_of_work.actions.get(f"action-{suffix}")
        approval = unit_of_work.approvals.get_active_for_action(f"action-{suffix}")
    assert action is not None
    assert action.status == "APPROVED"
    assert action.version == 1
    assert action.risk["duplicate"]["freshness"] == "FRESH_GOOGLE_GET"  # type: ignore[index]
    assert approval is not None
    claim = ClaimWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
        signing_secret="duplicate-preflight-secret",
        service_instance_id="duplicate-preflight-service",
    )(
        ClaimWriteActionCommand(
            command_id="claim-fresh-same",
            request_hash="ab" * 32,
            action_id=f"action-{suffix}",
            expected_version=1,
            source_snapshot={},
            attempt_id="attempt-fresh-same",
            nonce="nonce-fresh-same",
        )
    )
    assert claim.applied is True


def test_task_duplicate_preflight_source_failure_is_fail_closed(
    write_database: Path,
) -> None:
    clock = FakeClockPort(1000)
    suffix = "fresh-fail"
    _approve_preflight_action(
        write_database=write_database,
        clock=clock,
        suffix=suffix,
        risk=_duplicate_risk("NOT_DUPLICATE"),
    )
    gateway = _TaskDuplicatePreflightGateway(
        database_path=write_database,
        error=TimeoutError("source unavailable"),
    )

    with pytest.raises(TimeoutError, match="source unavailable"):
        PreflightWriteActionService(
            unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
            gateway=gateway,  # type: ignore[arg-type]
            now_ms=clock.now_ms,
        )(action_id=f"action-{suffix}")

    with sqlite_unit_of_work_factory(write_database)() as unit_of_work:
        action = unit_of_work.actions.get(f"action-{suffix}")
        approval = unit_of_work.approvals.get_active_for_action(f"action-{suffix}")
        events = unit_of_work.audits.list_page(
            AuditEventCursor(run_id="run-1", action_id=f"action-{suffix}"), 100
        )
    assert action is not None and action.status == "APPROVED" and action.version == 1
    assert approval is not None
    assert any(event.event_type == "TASK_DUPLICATE_PREFLIGHT_BLOCKED" for event in events)


def test_infeasible_action_cannot_be_approved(write_database: Path) -> None:
    clock = FakeClockPort(1000)
    suffix = "feasibility-blocked"
    response = _prepare_calendar_feasibility_action(
        write_database=write_database,
        clock=clock,
        suffix=suffix,
        risk=_feasibility_risk("INFEASIBLE", best_minutes=60),
    )
    assert response.applied is False
    assert response.conflict_detail == "work is infeasible before the business deadline"
    with sqlite_unit_of_work_factory(write_database)() as unit_of_work:
        approval = unit_of_work.approvals.get_active_for_action(f"action-{suffix}")
        events = unit_of_work.audits.list_page(
            AuditEventCursor(run_id="run-1", action_id=f"action-{suffix}"), 100
        )
    assert approval is None
    assert any(event.event_type == "FEASIBILITY_APPROVAL_BLOCKED" for event in events)


def test_feasibility_preflight_denial_blocks_run_before_claim(
    write_database: Path,
) -> None:
    clock = FakeClockPort(1000)
    suffix = "feasibility-change"
    assert (
        _prepare_calendar_feasibility_action(
            write_database=write_database,
            clock=clock,
            suffix=suffix,
            risk=_feasibility_risk("FEASIBLE", best_minutes=540),
        ).applied
        is True
    )
    busy = ResourceSnapshot(
        fixture_snapshot_id="busy",
        resource_type=ResourceType.CALENDAR_EVENT,
        resource_id="busy",
        parent_id="primary",
        related_resource_ids=("primary",),
        version="1",
        recovery_fingerprint=None,
        payload={
            "start": "1970-01-01T10:00:00+09:00",
            "end": "1970-01-01T18:00:00+09:00",
        },
    )

    with pytest.raises(PolicyViolationError, match="FEASIBILITY_BLOCKED"):
        PreflightWriteActionService(
            unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
            gateway=_FeasibilityPreflightGateway(busy_event=busy),  # type: ignore[arg-type]
            now_ms=clock.now_ms,
            work_hours_provider=lambda: CalendarWorkHours(timezone="Asia/Seoul"),
            **_stale_lifecycle_dependencies(write_database, clock),  # type: ignore[arg-type]
        )(action_id=f"action-{suffix}")

    with sqlite_unit_of_work_factory(write_database)() as unit_of_work:
        action = unit_of_work.actions.get(f"action-{suffix}")
        approval = unit_of_work.approvals.get_active_for_action(f"action-{suffix}")
        run = unit_of_work.runs.get("run-1")
    connection = connect_sqlite(write_database)
    try:
        attempt_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM execution_attempts AS attempt
            JOIN approvals AS approval ON approval.id = attempt.approval_id
            WHERE approval.action_id = ?
            """,
            (f"action-{suffix}",),
        ).fetchone()[0]
    finally:
        connection.close()
    assert action is not None and action.status == "BLOCKED"
    assert action.risk["feasibility"]["decision"] == "INFEASIBLE"  # type: ignore[index]
    assert approval is None
    assert run is not None and run.status.value == "BLOCKED"
    assert attempt_count == 0


def test_feasibility_preflight_same_snapshot_allows_claim(write_database: Path) -> None:
    clock = FakeClockPort(1000)
    suffix = "feasibility-same"
    assert (
        _prepare_calendar_feasibility_action(
            write_database=write_database,
            clock=clock,
            suffix=suffix,
            risk=_feasibility_risk("FEASIBLE", best_minutes=539),
        ).applied
        is True
    )
    PreflightWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        gateway=_FeasibilityPreflightGateway(),  # type: ignore[arg-type]
        now_ms=clock.now_ms,
        work_hours_provider=lambda: CalendarWorkHours(timezone="Asia/Seoul"),
    )(action_id=f"action-{suffix}")

    response = ClaimWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
        signing_secret="feasibility-secret",
        service_instance_id="feasibility-service",
    )(
        ClaimWriteActionCommand(
            command_id=f"claim-{suffix}",
            request_hash="a5" * 32,
            action_id=f"action-{suffix}",
            expected_version=1,
            source_snapshot={},
            attempt_id=f"attempt-{suffix}",
            nonce=f"nonce-{suffix}",
        )
    )
    assert response.applied is True
