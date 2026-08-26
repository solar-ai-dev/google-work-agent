"""Duplicate and feasibility policy integration tests."""

# ruff: noqa: F401

from __future__ import annotations

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

pytest_plugins = ("tests.integration.persistence.test_write_actions",)


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
        approvals = unit_of_work.approvals.list_by_action("action-dup-approval")
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
        events = unit_of_work.audits.list_by_aggregate(
            run_id="run-1", action_id="action-dup-replay"
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
        )(action_id=f"action-{suffix}")

    with sqlite_unit_of_work_factory(write_database)() as unit_of_work:
        action = unit_of_work.actions.get_by_id(f"action-{suffix}")
        approval = unit_of_work.approvals.get_active_by_action(f"action-{suffix}")
    assert action is not None
    assert action.status == "MODIFIED"
    assert action.version == 2
    assert action.risk["duplicate"]["freshness"] == "FRESH_GOOGLE_GET"  # type: ignore[index]
    assert approval is None


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
        action = unit_of_work.actions.get_by_id(f"action-{suffix}")
        approval = unit_of_work.approvals.get_active_by_action(f"action-{suffix}")
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
        action = unit_of_work.actions.get_by_id(f"action-{suffix}")
        approval = unit_of_work.approvals.get_active_by_action(f"action-{suffix}")
        events = unit_of_work.audits.list_by_aggregate(run_id="run-1", action_id=f"action-{suffix}")
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
        approval = unit_of_work.approvals.get_active_by_action(f"action-{suffix}")
        events = unit_of_work.audits.list_by_aggregate(run_id="run-1", action_id=f"action-{suffix}")
    assert approval is None
    assert any(event.event_type == "FEASIBILITY_APPROVAL_BLOCKED" for event in events)


def test_feasibility_preflight_change_revokes_approval_before_claim(
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

    with pytest.raises(PolicyViolationError, match="reapproval"):
        PreflightWriteActionService(
            unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
            gateway=_FeasibilityPreflightGateway(busy_event=busy),  # type: ignore[arg-type]
            now_ms=clock.now_ms,
            work_hours_provider=lambda: CalendarWorkHours(timezone="Asia/Seoul"),
        )(action_id=f"action-{suffix}")

    with sqlite_unit_of_work_factory(write_database)() as unit_of_work:
        action = unit_of_work.actions.get_by_id(f"action-{suffix}")
        approval = unit_of_work.approvals.get_active_by_action(f"action-{suffix}")
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
    assert action is not None and action.status == "MODIFIED"
    assert action.risk["feasibility"]["decision"] == "INFEASIBLE"  # type: ignore[index]
    assert approval is None
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
