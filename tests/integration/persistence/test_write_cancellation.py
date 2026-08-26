"""Write cancellation and cancel-recovery integration tests."""

# ruff: noqa: F401

from __future__ import annotations

from tests.integration.persistence.test_write_actions import (
    ApproveWriteActionCommand,
    ApproveWriteActionService,
    ClaimWriteActionCommand,
    ClaimWriteActionService,
    ExecuteWriteActionService,
    FakeClockPort,
    FakeGoogleGateway,
    FinalizeRunCancellationCommand,
    FinalizeRunCancellationService,
    GoogleGatewayFault,
    GoogleGatewayFaultKind,
    GoogleWorkspaceErrorCode,
    GoogleWorkspaceGatewayError,
    MarkWriteActionUnknownResultCommand,
    MarkWriteActionUnknownResultService,
    Path,
    QueryService,
    RecoverUnknownCreateActionCommand,
    RecoverUnknownCreateActionService,
    RequestRunCancellationCommand,
    RequestRunCancellationService,
    ResultCode,
    StoreWriteActionSuccessCommand,
    StoreWriteActionSuccessService,
    VerifyWriteActionCommand,
    VerifyWriteActionService,
    _action_cancelled_audit_count,
    _cancel_child_snapshot,
    _cancel_marker_count,
    _command_rejected_hash_mismatch_events,
    _insert_action_sibling,
    _prepare_claimed_action,
    _prepare_write_plan,
    _run_version,
    _seed_write_terminal_status,
    connect_sqlite,
    loads,
    pytest,
    sqlite_unit_of_work_factory,
)

pytest_plugins = ("tests.integration.persistence.test_write_actions",)


def test_waiting_approval_cancel_revokes_approval_and_finalizes_cancelled(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    del fixture_gateway
    clock = FakeClockPort(1000)
    _prepare_write_plan(write_database=write_database, clock=clock, suffix="cancel")
    approve_service = ApproveWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )
    approve_service(
        ApproveWriteActionCommand(
            command_id="approve-cancel",
            request_hash="w1" * 32,
            action_id="action-cancel",
            expected_version=0,
            approved_by_account_id="account-1",
            approved_by_display="User",
            source_snapshot={},
            approval_id="approval-cancel",
            idempotency_key="w2" * 32,
        )
    )
    request_cancel_service = RequestRunCancellationService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )
    cancelled = request_cancel_service(
        RequestRunCancellationCommand(
            command_id="cancel-request-1",
            request_hash="w3" * 32,
            run_id="run-1",
            expected_run_version=1,
        )
    )
    assert cancelled.applied is True
    assert cancelled.run_status == "CANCELLED"

    connection = connect_sqlite(write_database)
    try:
        rows = connection.execute(
            """
            SELECT
                (SELECT status FROM runs WHERE id = 'run-1') AS run_status,
                (SELECT status FROM plans WHERE id = 'plan-cancel') AS plan_status,
                (SELECT status FROM approvals WHERE id = 'approval-cancel') AS approval_status,
                (SELECT status FROM actions WHERE id = 'action-cancel') AS action_status,
                (SELECT COUNT(*) FROM execution_attempts) AS attempt_count,
                (SELECT COUNT(*) FROM verifications) AS verification_count;
            """
        ).fetchone()
        assert tuple(rows) == (
            "CANCELLED",
            "CANCELLED",
            "REVOKED",
            "CANCELLED",
            0,
            0,
        )
        audit = connection.execute(
            """
            SELECT action_id, outcome, metadata_json
            FROM audit_events
            WHERE event_type = 'ACTION_CANCELLED';
            """
        ).fetchone()
        assert audit["action_id"] == "action-cancel"
        assert audit["outcome"] == ResultCode.TRANSITION_APPLIED.value
        assert loads(audit["metadata_json"])["attributes"]["previous_status"] == "APPROVED"
    finally:
        connection.close()


@pytest.mark.parametrize("run_status", ("PLANNING", "WAITING_CONFIRMATION"))
def test_pre_plan_cancel_finalizes_without_creating_children(
    write_database: Path,
    run_status: str,
) -> None:
    connection = connect_sqlite(write_database)
    try:
        connection.execute("UPDATE runs SET status = ? WHERE id = 'run-1';", (run_status,))
        connection.commit()
    finally:
        connection.close()
    result = RequestRunCancellationService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=lambda: 1000,
    )(
        RequestRunCancellationCommand(
            command_id=f"cancel-pre-plan-{run_status}",
            request_hash="c7" * 32,
            run_id="run-1",
            expected_run_version=0,
        )
    )

    assert result.run_status == "CANCELLED"
    connection = connect_sqlite(write_database)
    try:
        counts = connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM plans),
                (SELECT COUNT(*) FROM actions),
                (SELECT COUNT(*) FROM execution_attempts),
                (SELECT COUNT(*) FROM verifications);
            """
        ).fetchone()
        assert tuple(counts) == (0, 0, 0, 0)
    finally:
        connection.close()


def test_cancel_version_and_hash_conflicts_are_atomic_and_replay_is_idempotent(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    del fixture_gateway
    clock = FakeClockPort(1000)
    _prepare_write_plan(write_database=write_database, clock=clock, suffix="atomic-cancel")
    ApproveWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )(
        ApproveWriteActionCommand(
            command_id="approve-atomic-cancel",
            request_hash="d7" * 32,
            action_id="action-atomic-cancel",
            expected_version=0,
            approved_by_account_id="account-1",
            approved_by_display="User",
            source_snapshot={},
            approval_id="approval-atomic-cancel",
            idempotency_key="d8" * 32,
        )
    )
    service = RequestRunCancellationService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )

    conflict = service(
        RequestRunCancellationCommand(
            command_id="cancel-version-conflict",
            request_hash="d9" * 32,
            run_id="run-1",
            expected_run_version=99,
        )
    )
    assert conflict.result_code == ResultCode.VERSION_CONFLICT.value
    assert _cancel_marker_count(write_database) == 0
    assert _cancel_child_snapshot(write_database) == (
        "WAITING_APPROVAL",
        1,
        "ACTIVE",
        "APPROVED",
        1,
        "ACTIVE",
    )

    command = RequestRunCancellationCommand(
        command_id="cancel-atomic-success",
        request_hash="e9" * 32,
        run_id="run-1",
        expected_run_version=1,
    )
    first = service(command)
    snapshot = _cancel_child_snapshot(write_database)
    replay = service(command)

    assert first == replay
    # B: a same-hash idempotent replay is not a rejection.
    assert _command_rejected_hash_mismatch_events(write_database) == ()

    hash_conflict = service(
        RequestRunCancellationCommand(
            command_id=command.command_id,
            request_hash="f9" * 32,
            run_id=command.run_id,
            expected_run_version=command.expected_run_version,
        )
    )

    assert hash_conflict.result_code == ResultCode.DUPLICATE_COMMAND.value
    assert _cancel_marker_count(write_database) == 1
    assert _action_cancelled_audit_count(write_database) == 1
    assert _cancel_child_snapshot(write_database) == snapshot

    # A: exactly one rejection event for the genuine different-hash conflict.
    rejection_events = _command_rejected_hash_mismatch_events(write_database)
    assert len(rejection_events) == 1
    envelope, outcome = rejection_events[0]
    assert outcome == ResultCode.DUPLICATE_COMMAND.value
    assert envelope["attributes"] == {
        "command_id": command.command_id,
        "command_type": "RequestRunCancellation",
        "result_code": ResultCode.DUPLICATE_COMMAND.value,
    }
    assert envelope["result_code"] == ResultCode.DUPLICATE_COMMAND.value
    assert envelope["correlation"]["run_id"] == command.run_id
    assert envelope["correlation"]["action_id"] is None
    # No raw payload/secret sneaks in beyond the allowlisted identifiers.
    raw = str(envelope)
    assert "arguments" not in raw
    assert "token" not in raw.lower()
    assert "secret" not in raw.lower()


def test_executing_cancel_waits_for_external_result_without_new_attempt(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClockPort(1000)
    claimed = _prepare_claimed_action(
        write_database=write_database,
        clock=clock,
        suffix="cancel-executing",
    )
    result = RequestRunCancellationService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )(
        RequestRunCancellationCommand(
            command_id="cancel-executing",
            request_hash="a6" * 32,
            run_id="run-1",
            expected_run_version=_run_version(write_database),
        )
    )

    assert result.run_status == "CANCEL_REQUESTED"
    blocked_claim = ClaimWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
        signing_secret="phase-e-secret",
        service_instance_id="write-svc-1",
    )(
        ClaimWriteActionCommand(
            command_id="claim-after-cancel",
            request_hash="f6" * 32,
            action_id="action-cancel-executing",
            expected_version=2,
            source_snapshot={},
            attempt_id="attempt-after-cancel",
            nonce="nonce-after-cancel",
        )
    )
    assert blocked_claim.applied is False
    assert blocked_claim.conflict_detail == "durable cancel intent forbids a new write claim"
    with pytest.raises(PermissionError, match="cancellation forbids"):
        ExecuteWriteActionService(
            unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
            gateway=fixture_gateway,
            now_ms=clock.now_ms,
            signing_secret="phase-e-secret",
            service_instance_id="write-svc-1",
        )(
            action_id="action-cancel-executing",
            claim_token=claimed.claim_token or "",
        )
    connection = connect_sqlite(write_database)
    try:
        row = connection.execute(
            "SELECT status, (SELECT COUNT(*) FROM execution_attempts) FROM runs WHERE id = 'run-1';"
        ).fetchone()
        assert tuple(row) == ("CANCEL_REQUESTED", 1)
    finally:
        connection.close()


def test_executed_cancel_moves_run_to_verifying_without_cancelling_result(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClockPort(1000)
    claimed = _prepare_claimed_action(
        write_database=write_database,
        clock=clock,
        suffix="cancel-executed",
    )
    executed = ExecuteWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        gateway=fixture_gateway,
        now_ms=clock.now_ms,
        signing_secret="phase-e-secret",
        service_instance_id="write-svc-1",
    )(
        action_id="action-cancel-executed",
        claim_token=claimed.claim_token or "",
    )
    StoreWriteActionSuccessService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )(
        StoreWriteActionSuccessCommand(
            command_id="store-cancel-executed",
            request_hash="a8" * 32,
            action_id="action-cancel-executed",
            attempt_id="attempt-cancel-executed",
            expected_action_version=2,
            expected_attempt_version=0,
            snapshot=executed.snapshot,
        )
    )
    _insert_action_sibling(
        database_path=write_database,
        source_action_id="action-cancel-executed",
        sibling_action_id="action-cancel-executed-sibling",
        status="CANCELLED",
    )
    RequestRunCancellationService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )(
        RequestRunCancellationCommand(
            command_id="cancel-executed",
            request_hash="b8" * 32,
            run_id="run-1",
            expected_run_version=_run_version(write_database),
        )
    )
    finalized = FinalizeRunCancellationService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )(
        FinalizeRunCancellationCommand(
            command_id="finalize-cancel-executed",
            request_hash="c8" * 32,
            run_id="run-1",
            expected_run_version=_run_version(write_database),
        )
    )

    assert finalized.run_status == "VERIFYING"
    assert finalized.result_kind is None
    snapshot = QueryService(
        database_path=write_database,
        connection_factory=connect_sqlite,
        runtime_status_provider=None,  # type: ignore[arg-type]
    ).get_run_snapshot("run-1")
    assert snapshot is not None
    assert snapshot.result_kind is None
    connection = connect_sqlite(write_database)
    try:
        row = connection.execute(
            """
            SELECT status, (SELECT COUNT(*) FROM verifications)
            FROM actions WHERE id = 'action-cancel-executed';
            """
        ).fetchone()
        assert tuple(row) == ("EXECUTED", 0)
    finally:
        connection.close()


def test_verified_partial_cancel_preserves_fact_and_cancels_pending_sibling(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClockPort(1000)
    claimed = _prepare_claimed_action(
        write_database=write_database,
        clock=clock,
        suffix="cancel-partial",
    )
    executed = ExecuteWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        gateway=fixture_gateway,
        now_ms=clock.now_ms,
        signing_secret="phase-e-secret",
        service_instance_id="write-svc-1",
    )(
        action_id="action-cancel-partial",
        claim_token=claimed.claim_token or "",
    )
    StoreWriteActionSuccessService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )(
        StoreWriteActionSuccessCommand(
            command_id="store-cancel-partial",
            request_hash="d8" * 32,
            action_id="action-cancel-partial",
            attempt_id="attempt-cancel-partial",
            expected_action_version=2,
            expected_attempt_version=0,
            snapshot=executed.snapshot,
        )
    )
    VerifyWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
        gateway=fixture_gateway,
    )(
        VerifyWriteActionCommand(
            command_id="verify-cancel-partial",
            request_hash="e8" * 32,
            action_id="action-cancel-partial",
            attempt_id="attempt-cancel-partial",
            expected_action_version=3,
            verification_id="verification-cancel-partial",
        )
    )
    connection = connect_sqlite(write_database)
    try:
        connection.execute(
            """
            INSERT INTO actions (
                id, plan_id, position, tool_name, effect_type, approval_requirement,
                verification_policy, recovery_policy, target_resource_ref_id, status,
                arguments_json, arguments_hash, expected_json, risk_json, version,
                created_at_ms, updated_at_ms
            )
            SELECT
                'action-cancel-pending', plan_id, 2, tool_name, effect_type,
                approval_requirement, verification_policy, recovery_policy,
                target_resource_ref_id, 'PROPOSED', arguments_json, arguments_hash,
                expected_json, risk_json, 0, created_at_ms, updated_at_ms
            FROM actions WHERE id = 'action-cancel-partial';
            """
        )
        connection.commit()
    finally:
        connection.close()

    RequestRunCancellationService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )(
        RequestRunCancellationCommand(
            command_id="cancel-partial",
            request_hash="f8" * 32,
            run_id="run-1",
            expected_run_version=_run_version(write_database),
        )
    )
    finalized = FinalizeRunCancellationService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )(
        FinalizeRunCancellationCommand(
            command_id="finalize-cancel-partial",
            request_hash="a9" * 32,
            run_id="run-1",
            expected_run_version=_run_version(write_database),
        )
    )

    assert finalized.run_status == "CANCELLED"
    assert finalized.result_kind == "PARTIAL"
    snapshot = QueryService(
        database_path=write_database,
        connection_factory=connect_sqlite,
        runtime_status_provider=None,  # type: ignore[arg-type]
    ).get_run_snapshot("run-1")
    assert snapshot is not None
    assert snapshot.result_kind == "PARTIAL"
    assert snapshot.execution_status["terminal_action_count"] == 2
    connection = connect_sqlite(write_database)
    try:
        rows = connection.execute(
            """
            SELECT id, status FROM actions
            WHERE id IN ('action-cancel-partial', 'action-cancel-pending')
            ORDER BY id;
            """
        ).fetchall()
        assert [tuple(row) for row in rows] == [
            ("action-cancel-partial", "VERIFIED"),
            ("action-cancel-pending", "CANCELLED"),
        ]
        assert connection.execute("SELECT COUNT(*) FROM verifications;").fetchone()[0] == 1
        assert (
            connection.execute(
                """
            SELECT COUNT(*) FROM audit_events
            WHERE event_type = 'ACTION_CANCELLED'
              AND action_id = 'action-cancel-pending';
            """
            ).fetchone()[0]
            == 1
        )
    finally:
        connection.close()


def test_unknown_result_cancel_enters_recovery_without_blind_retry(
    write_database: Path,
) -> None:
    clock = FakeClockPort(1000)
    _prepare_claimed_action(
        write_database=write_database,
        clock=clock,
        suffix="cancel-unknown",
    )
    MarkWriteActionUnknownResultService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )(
        MarkWriteActionUnknownResultCommand(
            command_id="unknown-cancel",
            request_hash="b6" * 32,
            action_id="action-cancel-unknown",
            attempt_id="attempt-cancel-unknown",
            expected_action_version=2,
            expected_attempt_version=0,
            error_code=GoogleWorkspaceErrorCode.TIMEOUT.value,
            error_detail="dispatch outcome unknown",
        )
    )
    _insert_action_sibling(
        database_path=write_database,
        source_action_id="action-cancel-unknown",
        sibling_action_id="action-cancel-unknown-sibling",
        status="CANCELLED",
    )
    RequestRunCancellationService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )(
        RequestRunCancellationCommand(
            command_id="cancel-unknown",
            request_hash="c6" * 32,
            run_id="run-1",
            expected_run_version=_run_version(write_database),
        )
    )
    finalized = FinalizeRunCancellationService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )(
        FinalizeRunCancellationCommand(
            command_id="finalize-cancel-unknown",
            request_hash="d6" * 32,
            run_id="run-1",
            expected_run_version=_run_version(write_database),
        )
    )

    assert finalized.run_status == "RECOVERY_REQUIRED"
    snapshot = QueryService(
        database_path=write_database,
        connection_factory=connect_sqlite,
        runtime_status_provider=None,  # type: ignore[arg-type]
    ).get_run_snapshot("run-1")
    assert snapshot is not None
    assert snapshot.result_kind is None
    connection = connect_sqlite(write_database)
    try:
        counts = connection.execute(
            "SELECT COUNT(*), COUNT(DISTINCT id) FROM execution_attempts;"
        ).fetchone()
        assert tuple(counts) == (1, 1)
    finally:
        connection.close()


@pytest.mark.parametrize("terminal_status", ("MISMATCH", "FAILED"))
def test_non_success_terminal_action_with_cancelled_sibling_is_not_partial(
    write_database: Path,
    terminal_status: str,
) -> None:
    clock = FakeClockPort(1000)
    suffix = f"cancel-{terminal_status.lower()}"
    _prepare_write_plan(write_database=write_database, clock=clock, suffix=suffix)
    _seed_write_terminal_status(
        database_path=write_database,
        action_id=f"action-{suffix}",
        terminal_status=terminal_status,
    )
    _insert_action_sibling(
        database_path=write_database,
        source_action_id=f"action-{suffix}",
        sibling_action_id=f"action-{suffix}-pending",
        status="PROPOSED",
    )

    result = RequestRunCancellationService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )(
        RequestRunCancellationCommand(
            command_id=f"request-{suffix}",
            request_hash="ab" * 32,
            run_id="run-1",
            expected_run_version=_run_version(write_database),
        )
    )

    assert result.run_status == "CANCELLED"
    assert result.result_kind == "CANCELLED"
    snapshot = QueryService(
        database_path=write_database,
        connection_factory=connect_sqlite,
        runtime_status_provider=None,  # type: ignore[arg-type]
    ).get_run_snapshot("run-1")
    assert snapshot is not None
    assert snapshot.result_kind == "CANCELLED"
    assert {action.status for action in snapshot.actions} == {terminal_status, "CANCELLED"}


def test_unknown_recovery_preserves_one_cancel_marker_and_finalizes_through_domain_commands(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClockPort(1000)
    claimed = _prepare_claimed_action(
        write_database=write_database,
        clock=clock,
        suffix="cancel-recovery",
    )
    fixture_gateway.queue_fault(
        operation="create_task",
        fault=GoogleGatewayFault(GoogleGatewayFaultKind.TIMEOUT_AFTER_DELIVERY),
    )
    with pytest.raises(GoogleWorkspaceGatewayError) as error_info:
        ExecuteWriteActionService(
            unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
            gateway=fixture_gateway,
            now_ms=clock.now_ms,
            signing_secret="phase-e-secret",
            service_instance_id="write-svc-1",
        )(
            action_id="action-cancel-recovery",
            claim_token=claimed.claim_token or "",
        )
    MarkWriteActionUnknownResultService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )(
        MarkWriteActionUnknownResultCommand(
            command_id="unknown-cancel-recovery",
            request_hash="bc" * 32,
            action_id="action-cancel-recovery",
            attempt_id="attempt-cancel-recovery",
            expected_action_version=2,
            expected_attempt_version=0,
            error_code=error_info.value.code.value,
            error_detail=str(error_info.value),
        )
    )
    _insert_action_sibling(
        database_path=write_database,
        source_action_id="action-cancel-recovery",
        sibling_action_id="action-cancel-recovery-pending",
        status="PROPOSED",
    )
    cancellation_requested = RequestRunCancellationService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )(
        RequestRunCancellationCommand(
            command_id="request-cancel-recovery",
            request_hash="bd" * 32,
            run_id="run-1",
            expected_run_version=_run_version(write_database),
        )
    )
    assert cancellation_requested.run_status == "CANCEL_REQUESTED"
    assert _cancel_marker_count(write_database) == 1
    recovery_required = FinalizeRunCancellationService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )(
        FinalizeRunCancellationCommand(
            command_id="finalize-cancel-recovery-1",
            request_hash="be" * 32,
            run_id="run-1",
            expected_run_version=_run_version(write_database),
        )
    )
    assert recovery_required.run_status == "RECOVERY_REQUIRED"

    recovered = RecoverUnknownCreateActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
        gateway=fixture_gateway,
    )(
        RecoverUnknownCreateActionCommand(
            command_id="recover-cancel-recovery",
            request_hash="bf" * 32,
            action_id="action-cancel-recovery",
            attempt_id="attempt-cancel-recovery",
            expected_action_version=3,
            expected_attempt_version=1,
        )
    )
    assert recovered.action_status == "EXECUTED"
    verified = VerifyWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
        gateway=fixture_gateway,
    )(
        VerifyWriteActionCommand(
            command_id="verify-cancel-recovery",
            request_hash="ca" * 32,
            action_id="action-cancel-recovery",
            attempt_id="attempt-cancel-recovery",
            expected_action_version=recovered.action_version,
            verification_id="verification-cancel-recovery",
        )
    )
    assert verified.action_status == "VERIFIED"

    finalized = FinalizeRunCancellationService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )(
        FinalizeRunCancellationCommand(
            command_id="finalize-cancel-recovery-2",
            request_hash="cb" * 32,
            run_id="run-1",
            expected_run_version=_run_version(write_database),
        )
    )

    assert finalized.run_status == "CANCELLED"
    assert finalized.result_kind == "PARTIAL"
    assert _cancel_marker_count(write_database) == 1
    assert fixture_gateway.count_calls("create_task") == 1
    connection = connect_sqlite(write_database)
    try:
        rows = connection.execute("SELECT id, status FROM actions ORDER BY position;").fetchall()
        assert [tuple(row) for row in rows] == [
            ("action-cancel-recovery", "VERIFIED"),
            ("action-cancel-recovery-pending", "CANCELLED"),
        ]
    finally:
        connection.close()


def test_recovery_without_successful_cancel_marker_cannot_finalize_cancel(
    write_database: Path,
) -> None:
    clock = FakeClockPort(1000)
    _prepare_write_plan(write_database=write_database, clock=clock, suffix="no-cancel-marker")
    connection = connect_sqlite(write_database)
    try:
        connection.execute("UPDATE runs SET status = 'RECOVERY_REQUIRED' WHERE id = 'run-1';")
        connection.commit()
    finally:
        connection.close()

    result = FinalizeRunCancellationService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )(
        FinalizeRunCancellationCommand(
            command_id="finalize-without-marker",
            request_hash="cc" * 32,
            run_id="run-1",
            expected_run_version=_run_version(write_database),
        )
    )

    assert result.applied is False
    assert result.result_code == ResultCode.STATE_CONFLICT.value
    assert result.run_status == "RECOVERY_REQUIRED"
    assert _cancel_marker_count(write_database) == 0
    connection = connect_sqlite(write_database)
    try:
        row = connection.execute(
            "SELECT (SELECT status FROM plans), (SELECT status FROM actions);"
        ).fetchone()
        assert tuple(row) == ("WAITING_APPROVAL", "PROPOSED")
    finally:
        connection.close()


def test_failed_cancel_audit_marker_does_not_authorize_verifying_continuation(
    write_database: Path,
) -> None:
    clock = FakeClockPort(1000)
    _prepare_write_plan(write_database=write_database, clock=clock, suffix="failed-marker")
    connection = connect_sqlite(write_database)
    try:
        connection.execute("UPDATE runs SET status = 'VERIFYING' WHERE id = 'run-1';")
        connection.execute(
            """
            INSERT INTO audit_events (
                account_id, run_id, action_id, actor_type, actor_id, actor_display,
                event_type, outcome, metadata_json, created_at_ms
            )
            VALUES (
                'account-1', 'run-1', NULL, 'USER', 'account-1', 'User',
                'RUN_CANCELLATION_REQUESTED', 'VERSION_CONFLICT', '{}', 1000
            );
            """
        )
        connection.commit()
    finally:
        connection.close()

    query_service = QueryService(
        database_path=write_database,
        connection_factory=connect_sqlite,
        runtime_status_provider=None,  # type: ignore[arg-type]
    )
    assert query_service.has_cancel_intent("run-1") is False
    result = FinalizeRunCancellationService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )(
        FinalizeRunCancellationCommand(
            command_id="finalize-failed-marker",
            request_hash="cf" * 32,
            run_id="run-1",
            expected_run_version=_run_version(write_database),
        )
    )

    assert result.applied is False
    assert result.result_code == ResultCode.STATE_CONFLICT.value
    assert result.run_status == "VERIFYING"
    connection = connect_sqlite(write_database)
    try:
        assert connection.execute("SELECT status FROM actions;").fetchone()[0] == "PROPOSED"
    finally:
        connection.close()


def test_cancel_marker_does_not_bypass_current_run_domain_guard(
    write_database: Path,
) -> None:
    clock = FakeClockPort(1000)
    _prepare_claimed_action(
        write_database=write_database,
        clock=clock,
        suffix="cancel-guard",
    )
    RequestRunCancellationService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )(
        RequestRunCancellationCommand(
            command_id="request-cancel-guard",
            request_hash="cd" * 32,
            run_id="run-1",
            expected_run_version=_run_version(write_database),
        )
    )
    connection = connect_sqlite(write_database)
    try:
        connection.execute("UPDATE runs SET status = 'REAUTH_REQUIRED' WHERE id = 'run-1';")
        connection.commit()
    finally:
        connection.close()

    result = FinalizeRunCancellationService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )(
        FinalizeRunCancellationCommand(
            command_id="finalize-cancel-guard",
            request_hash="ce" * 32,
            run_id="run-1",
            expected_run_version=_run_version(write_database),
        )
    )

    assert result.applied is False
    assert result.result_code == ResultCode.STATE_CONFLICT.value
    assert result.run_status == "REAUTH_REQUIRED"
    assert _cancel_marker_count(write_database) == 1
    connection = connect_sqlite(write_database)
    try:
        assert connection.execute("SELECT status FROM actions;").fetchone()[0] == "EXECUTING"
    finally:
        connection.close()
