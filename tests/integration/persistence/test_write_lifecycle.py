"""Write plan, claim, verification, and transaction tests."""

# ruff: noqa: F401

from __future__ import annotations

from tests.integration.persistence.test_write_actions import (
    ApproveWriteActionCommand,
    ApproveWriteActionService,
    ClaimWriteActionCommand,
    ClaimWriteActionService,
    EvidenceOriginType,
    ExecuteWriteActionService,
    FakeClock,
    FakeGoogleGateway,
    GoogleGatewayFault,
    GoogleGatewayFaultKind,
    GoogleWorkspaceExecutionBackend,
    GoogleWorkspaceGateway,
    Path,
    PublishWritePlanCommand,
    PublishWritePlanService,
    RecoveryResolutionKind,
    ResolveMismatchRecoveryCommand,
    ResolveMismatchRecoveryService,
    ResultCode,
    RunCommand,
    RunStatus,
    SaveWritePlanCommand,
    SaveWritePlanService,
    StoreWriteActionSuccessCommand,
    StoreWriteActionSuccessService,
    VerifyWriteActionCommand,
    VerifyWriteActionService,
    WriteActionDraft,
    WriteEvidenceDraft,
    _expected_task_projection,
    _insert_action_sibling,
    _prepare_claimed_action,
    _prepare_mismatch,
    _prepare_write_plan,
    _TransactionCheckingGateway,
    cast,
    connect_sqlite,
    pytest,
    sqlite_unit_of_work_factory,
)

pytest_plugins = ("tests.integration.persistence.test_write_actions",)


def test_run_recovery_commands_use_domain_transitions(write_database: Path) -> None:
    with sqlite_unit_of_work_factory(write_database)() as unit_of_work:
        required = unit_of_work.runs.require_recovery(
            "run-1",
            expected_version=0,
        )
        resolved = unit_of_work.runs.resolve_recovery(
            "run-1",
            expected_version=1,
            recovery_next_status=RunStatus.VERIFYING,
        )
        unit_of_work.commit()

    assert required.applied is True
    assert required.current_status is RunStatus.RECOVERY_REQUIRED
    assert required.next_allowed_commands == (
        RunCommand.REQUEST_CANCEL,
        RunCommand.RESOLVE_RECOVERY,
    )
    assert resolved.applied is True
    assert resolved.current_status is RunStatus.VERIFYING
    connection = connect_sqlite(write_database)
    try:
        row = connection.execute("SELECT status, version FROM runs WHERE id = 'run-1';").fetchone()
        assert tuple(row) == ("VERIFYING", 2)
    finally:
        connection.close()


def test_write_happy_path_requires_approval_then_executes_and_verifies(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClock(1000)
    save_service = SaveWritePlanService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )
    publish_service = PublishWritePlanService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )
    approve_service = ApproveWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )
    claim_service = ClaimWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
        signing_secret="phase-e-secret",
        service_instance_id="write-svc-1",
    )
    execute_service = ExecuteWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        gateway=fixture_gateway,
        now_ms=clock.now_ms,
        signing_secret="phase-e-secret",
        service_instance_id="write-svc-1",
    )
    store_success_service = StoreWriteActionSuccessService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )
    verify_service = VerifyWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
        gateway=fixture_gateway,
    )

    payload = {
        "resource_id": "task-created-1",
        "title": "Send summary",
        "status": "needsAction",
    }
    expected = _expected_task_projection(resource_id="task-created-1", payload=payload, version="1")
    save_response = save_service(
        SaveWritePlanCommand(
            command_id="save-write-1",
            request_hash="a1" * 32,
            plan_id="plan-write-1",
            run_id="run-1",
            revision_no=1,
            summary_text="create one task",
            expected_run_version=0,
            actions=(
                WriteActionDraft(
                    action_id="action-write-1",
                    position=1,
                    tool_name="tasks_create_task",
                    arguments={"task_list_id": "task-list-default", "payload": payload},
                    expected=expected,
                    evidence_ids=("evidence-write-1",),
                ),
            ),
            evidence=(
                WriteEvidenceDraft(
                    evidence_id="evidence-write-1",
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
            command_id="publish-write-1",
            request_hash="a2" * 32,
            plan_id="plan-write-1",
            run_id="run-1",
            expected_run_version=0,
        )
    )
    assert publish_response.applied is True
    assert publish_response.run_status == "WAITING_APPROVAL"
    assert publish_response.plan_status == "WAITING_APPROVAL"

    blocked_claim = claim_service(
        ClaimWriteActionCommand(
            command_id="claim-write-blocked",
            request_hash="a3" * 32,
            action_id="action-write-1",
            expected_version=0,
            source_snapshot={},
            attempt_id="attempt-blocked",
            nonce="nonce-blocked",
        )
    )
    assert blocked_claim.applied is False
    assert blocked_claim.result_code == ResultCode.STATE_CONFLICT.value

    approve_response = approve_service(
        ApproveWriteActionCommand(
            command_id="approve-write-1",
            request_hash="a4" * 32,
            action_id="action-write-1",
            expected_version=0,
            approved_by_account_id="account-1",
            approved_by_display="User",
            source_snapshot={},
            approval_id="approval-write-1",
            idempotency_key="b1" * 32,
        )
    )
    assert approve_response.applied is True
    assert approve_response.action_status == "APPROVED"

    claim_command = ClaimWriteActionCommand(
        command_id="claim-write-1",
        request_hash="a5" * 32,
        action_id="action-write-1",
        expected_version=1,
        source_snapshot={},
        attempt_id="attempt-write-1",
        nonce="nonce-write-1",
    )
    claimed_first = claim_service(claim_command)
    claimed_second = claim_service(claim_command)
    assert claimed_first.applied is True
    assert claimed_second == claimed_first
    assert claimed_first.action_status == "EXECUTING"
    assert claimed_first.attempt_id == "attempt-write-1"
    assert claimed_first.claim_token is not None

    executed = execute_service(
        action_id="action-write-1",
        claim_token=claimed_first.claim_token,
    )
    assert executed.snapshot.resource_id == "task-created-1"
    assert fixture_gateway.call_log[-1].operation == "create_task"

    stored = store_success_service(
        StoreWriteActionSuccessCommand(
            command_id="store-write-1",
            request_hash="a6" * 32,
            action_id="action-write-1",
            attempt_id="attempt-write-1",
            expected_action_version=2,
            expected_attempt_version=0,
            snapshot=executed.snapshot,
        )
    )
    assert stored.applied is True
    assert stored.action_status == "EXECUTED"

    verified = verify_service(
        VerifyWriteActionCommand(
            command_id="verify-write-1",
            request_hash="a7" * 32,
            action_id="action-write-1",
            attempt_id="attempt-write-1",
            expected_action_version=3,
            verification_id="verification-write-1",
        )
    )
    assert verified.applied is True
    assert verified.action_status == "VERIFIED"

    connection = connect_sqlite(write_database)
    try:
        action_row = connection.execute(
            "SELECT status, version FROM actions WHERE id = 'action-write-1';"
        ).fetchone()
        plan_row = connection.execute(
            "SELECT status FROM plans WHERE id = 'plan-write-1';"
        ).fetchone()
        approval_row = connection.execute(
            "SELECT status, consumed_at_ms FROM approvals WHERE id = 'approval-write-1';"
        ).fetchone()
        attempt_row = connection.execute(
            """
            SELECT status, version, result_resource_ref_id
            FROM execution_attempts
            WHERE id = 'attempt-write-1';
            """
        ).fetchone()
        verification_row = connection.execute(
            """
            SELECT status, expected_json, actual_json
            FROM verifications
            WHERE id = 'verification-write-1';
            """
        ).fetchone()
        resource_row = connection.execute(
            """
            SELECT resource_id, version_token
            FROM resource_refs
            WHERE id = 'resource-ref-run-1-task-task-created-1';
            """
        ).fetchone()
        attempt_count = connection.execute(
            "SELECT COUNT(*) FROM execution_attempts WHERE approval_id = 'approval-write-1';"
        ).fetchone()[0]

        assert action_row["status"] == "VERIFIED"
        assert action_row["version"] == 4
        assert plan_row["status"] == "ACTIVE"
        assert approval_row["status"] == "CONSUMED"
        assert approval_row["consumed_at_ms"] is not None
        assert attempt_row["status"] == "SUCCEEDED"
        assert attempt_row["version"] == 1
        assert attempt_row["result_resource_ref_id"] == "resource-ref-run-1-task-task-created-1"
        assert verification_row["status"] == "VERIFIED"
        assert '"resource_id":"task-created-1"' in verification_row["expected_json"]
        assert '"resource_id":"task-created-1"' in verification_row["actual_json"]
        assert resource_row["resource_id"] == "task-created-1"
        assert resource_row["version_token"] == "1"
        assert attempt_count == 1
    finally:
        connection.close()


def test_claim_is_blocked_by_missing_approval_and_source_hash_mismatch(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    del fixture_gateway
    clock = FakeClock(1000)
    _prepare_write_plan(
        write_database=write_database,
        clock=clock,
        suffix="block",
    )

    claim_service = ClaimWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
        signing_secret="phase-e-secret",
        service_instance_id="write-svc-1",
    )
    blocked = claim_service(
        ClaimWriteActionCommand(
            command_id="claim-block-1",
            request_hash="b2" * 32,
            action_id="action-block",
            expected_version=0,
            source_snapshot={},
            attempt_id="attempt-block-1",
            nonce="nonce-block-1",
        )
    )
    assert blocked.applied is False
    assert blocked.result_code == ResultCode.STATE_CONFLICT.value

    approve_service = ApproveWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )
    approve_service(
        ApproveWriteActionCommand(
            command_id="approve-block-1",
            request_hash="b3" * 32,
            action_id="action-block",
            expected_version=0,
            approved_by_account_id="account-1",
            approved_by_display="User",
            source_snapshot={},
            approval_id="approval-block-1",
            idempotency_key="b4" * 32,
        )
    )

    mismatched = claim_service(
        ClaimWriteActionCommand(
            command_id="claim-block-2",
            request_hash="b5" * 32,
            action_id="action-block",
            expected_version=1,
            source_snapshot={"snapshot": "changed"},
            attempt_id="attempt-block-2",
            nonce="nonce-block-2",
        )
    )
    assert mismatched.applied is False
    assert "source snapshot hash" in (mismatched.conflict_detail or "")

    connection = connect_sqlite(write_database)
    try:
        counts = connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM execution_attempts) AS attempt_count,
                (SELECT COUNT(*) FROM approvals WHERE status = 'ACTIVE') AS active_approval_count;
            """
        ).fetchone()
        assert tuple(counts) == (0, 1)
    finally:
        connection.close()


def test_claim_token_binding_expiry_and_replay_are_blocked(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClock(1000)
    claimed = _prepare_claimed_action(
        write_database=write_database,
        clock=clock,
        suffix="token-a",
    )

    wrong_service = ExecuteWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        gateway=fixture_gateway,
        now_ms=clock.now_ms,
        signing_secret="phase-e-secret",
        service_instance_id="write-svc-2",
    )
    with pytest.raises(PermissionError, match="service binding mismatch"):
        wrong_service(action_id="action-token-a", claim_token=claimed.claim_token or "")

    execute_service = ExecuteWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        gateway=fixture_gateway,
        now_ms=clock.now_ms,
        signing_secret="phase-e-secret",
        service_instance_id="write-svc-1",
    )
    execute_service(action_id="action-token-a", claim_token=claimed.claim_token or "")
    with pytest.raises(PermissionError, match="already been used"):
        execute_service(action_id="action-token-a", claim_token=claimed.claim_token or "")

    claimed_expiring = _prepare_claimed_action(
        write_database=write_database,
        clock=clock,
        suffix="token-b",
        run_id="run-2",
    )
    clock.advance_ms(30_001)
    expiring_service = ExecuteWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        gateway=fixture_gateway,
        now_ms=clock.now_ms,
        signing_secret="phase-e-secret",
        service_instance_id="write-svc-1",
    )
    with pytest.raises(PermissionError, match="expired"):
        expiring_service(
            action_id="action-token-b",
            claim_token=claimed_expiring.claim_token or "",
        )


def test_verification_mismatch_is_persisted_without_auto_verifying_tool_response(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClock(1000)
    claimed = _prepare_claimed_action(
        write_database=write_database,
        clock=clock,
        suffix="mismatch",
    )
    execute_service = ExecuteWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        gateway=fixture_gateway,
        now_ms=clock.now_ms,
        signing_secret="phase-e-secret",
        service_instance_id="write-svc-1",
    )
    stored_service = StoreWriteActionSuccessService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )
    verify_service = VerifyWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
        gateway=fixture_gateway,
    )

    executed = execute_service(
        action_id="action-mismatch",
        claim_token=claimed.claim_token or "",
    )
    stored_service(
        StoreWriteActionSuccessCommand(
            command_id="store-mismatch",
            request_hash="c1" * 32,
            action_id="action-mismatch",
            attempt_id="attempt-mismatch",
            expected_action_version=2,
            expected_attempt_version=0,
            snapshot=executed.snapshot,
        )
    )
    fixture_gateway.queue_fault(
        operation="get_task",
        fault=GoogleGatewayFault(GoogleGatewayFaultKind.VERIFICATION_MISMATCH),
    )

    verified = verify_service(
        VerifyWriteActionCommand(
            command_id="verify-mismatch",
            request_hash="c2" * 32,
            action_id="action-mismatch",
            attempt_id="attempt-mismatch",
            expected_action_version=3,
            verification_id="verification-mismatch",
        )
    )
    assert verified.applied is True
    assert verified.action_status == "MISMATCH"

    connection = connect_sqlite(write_database)
    try:
        rows = connection.execute(
            """
            SELECT
                (SELECT status FROM actions WHERE id = 'action-mismatch') AS action_status,
                (
                    SELECT status
                    FROM verifications
                    WHERE id = 'verification-mismatch'
                ) AS verification_status,
                (
                    SELECT r.status
                    FROM runs AS r
                    JOIN plans AS p ON p.run_id = r.id
                    JOIN actions AS a ON a.plan_id = p.id
                    WHERE a.id = 'action-mismatch'
                ) AS run_status,
                (SELECT COUNT(*) FROM verifications WHERE status = 'VERIFIED') AS verified_count;
            """
        ).fetchone()
        assert tuple(rows) == ("MISMATCH", "MISMATCH", "RECOVERY_REQUIRED", 0)
    finally:
        connection.close()


def test_accept_partial_preserves_mismatch_and_cancels_pending_actions(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    run_version = _prepare_mismatch(
        write_database=write_database,
        gateway=fixture_gateway,
        suffix="accept-partial",
    )
    connection = connect_sqlite(write_database)
    try:
        source = connection.execute(
            "SELECT * FROM actions WHERE id = 'action-accept-partial';"
        ).fetchone()
        connection.execute(
            """
            INSERT INTO actions (
                id, plan_id, position, tool_name, effect_type, approval_requirement,
                verification_policy, recovery_policy, target_resource_ref_id, status,
                arguments_json, arguments_hash, expected_json, risk_json, version,
                created_at_ms, updated_at_ms
            ) VALUES (?, ?, 2, ?, ?, ?, ?, ?, NULL, 'PROPOSED', ?, ?, ?, '{}', 0, 1000, 1000);
            """,
            (
                "action-pending-after-mismatch",
                source["plan_id"],
                source["tool_name"],
                source["effect_type"],
                source["approval_requirement"],
                source["verification_policy"],
                source["recovery_policy"],
                source["arguments_json"],
                source["arguments_hash"],
                source["expected_json"],
            ),
        )
        connection.commit()
    finally:
        connection.close()

    service = ResolveMismatchRecoveryService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=lambda: 2000,
    )
    result = service(
        ResolveMismatchRecoveryCommand(
            command_id="resolve-accept-partial",
            request_hash="a9" * 32,
            run_id="run-1",
            action_id="action-accept-partial",
            expected_run_version=run_version,
            resolution_kind=RecoveryResolutionKind.ACCEPT_PARTIAL,
        )
    )

    assert result.applied is True
    assert result.run_status == "COMPLETED"
    assert result.result_kind == "PARTIAL"
    connection = connect_sqlite(write_database)
    try:
        facts = connection.execute(
            """
            SELECT
                (SELECT status FROM actions WHERE id = 'action-accept-partial'),
                (SELECT status FROM actions WHERE id = 'action-pending-after-mismatch'),
                (SELECT COUNT(*) FROM execution_attempts),
                (SELECT COUNT(*) FROM verifications);
            """
        ).fetchone()
        assert tuple(facts) == ("MISMATCH", "CANCELLED", 1, 1)
    finally:
        connection.close()


def test_corrective_recovery_creates_fresh_plan_revision_without_reusing_facts(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    run_version = _prepare_mismatch(
        write_database=write_database,
        gateway=fixture_gateway,
        suffix="corrective",
    )
    _insert_action_sibling(
        database_path=write_database,
        source_action_id="action-corrective",
        sibling_action_id="action-corrective-pending",
        status="APPROVED",
    )
    connection = connect_sqlite(write_database)
    try:
        connection.execute(
            """
            INSERT INTO approvals (
                id, action_id, approval_no, action_version, status, approved_by_account_id,
                arguments_snapshot_json, canonical_arguments_hash, source_snapshot_json,
                source_snapshot_hash, policy_version, tool_schema_version, idempotency_key,
                recovery_fingerprint, approved_at_ms, expires_at_ms
            ) VALUES (
                'approval-corrective-pending', 'action-corrective-pending', 1, 0, 'ACTIVE',
                'account-1', '{}', ?, '{}', ?, 'p1', 'v1', ?, ?, 1, 3000
            );
            """,
            ("a" * 64, "b" * 64, "c" * 64, "d" * 64),
        )
        connection.commit()
    finally:
        connection.close()
    service = ResolveMismatchRecoveryService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=lambda: 2000,
    )

    result = service(
        ResolveMismatchRecoveryCommand(
            command_id="resolve-corrective",
            request_hash="b9" * 32,
            run_id="run-1",
            action_id="action-corrective",
            expected_run_version=run_version,
            resolution_kind=RecoveryResolutionKind.CREATE_CORRECTIVE_PLAN,
            corrective_plan_id="plan-corrective-v2",
        )
    )

    assert result.applied is True
    assert result.run_status == "PLANNING"
    connection = connect_sqlite(write_database)
    try:
        plans = connection.execute(
            "SELECT id, revision_no, status FROM plans ORDER BY revision_no;"
        ).fetchall()
        counts = connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM actions),
                (SELECT COUNT(*) FROM approvals),
                (SELECT COUNT(*) FROM execution_attempts),
                (SELECT COUNT(*) FROM verifications);
            """
        ).fetchone()
        pending_approval_status = connection.execute(
            "SELECT status FROM approvals WHERE id = 'approval-corrective-pending';"
        ).fetchone()[0]
        assert [tuple(row) for row in plans] == [
            ("plan-corrective", 1, "SUPERSEDED"),
            ("plan-corrective-v2", 2, "DRAFT"),
        ]
        assert tuple(counts) == (2, 2, 1, 1)
        assert pending_approval_status == "REVOKED"
    finally:
        connection.close()


def test_verify_write_action_get_runs_without_sqlite_write_transaction(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClock(1000)
    claimed = _prepare_claimed_action(
        write_database=write_database,
        clock=clock,
        suffix="verify-boundary",
    )
    execute_service = ExecuteWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        gateway=fixture_gateway,
        now_ms=clock.now_ms,
        signing_secret="phase-e-secret",
        service_instance_id="write-svc-1",
    )
    stored_service = StoreWriteActionSuccessService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )
    executed = execute_service(
        action_id="action-verify-boundary",
        claim_token=claimed.claim_token or "",
    )
    stored_service(
        StoreWriteActionSuccessCommand(
            command_id="store-verify-boundary",
            request_hash="j1" * 32,
            action_id="action-verify-boundary",
            attempt_id="attempt-verify-boundary",
            expected_action_version=2,
            expected_attempt_version=0,
            snapshot=executed.snapshot,
        )
    )
    verify_service = VerifyWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
        gateway=GoogleWorkspaceExecutionBackend(
            gateway=cast(
                GoogleWorkspaceGateway,
                _TransactionCheckingGateway(
                    delegate=fixture_gateway,
                    database_path=write_database,
                ),
            )
        ),
    )

    verified = verify_service(
        VerifyWriteActionCommand(
            command_id="verify-boundary",
            request_hash="j2" * 32,
            action_id="action-verify-boundary",
            attempt_id="attempt-verify-boundary",
            expected_action_version=3,
            verification_id="verification-boundary",
        )
    )

    assert verified.applied is True
    assert verified.action_status == "VERIFIED"


def test_verify_write_action_rechecks_version_after_external_get(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClock(1000)
    claimed = _prepare_claimed_action(
        write_database=write_database,
        clock=clock,
        suffix="verify-race",
    )
    execute_service = ExecuteWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        gateway=fixture_gateway,
        now_ms=clock.now_ms,
        signing_secret="phase-e-secret",
        service_instance_id="write-svc-1",
    )
    stored_service = StoreWriteActionSuccessService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )
    executed = execute_service(
        action_id="action-verify-race",
        claim_token=claimed.claim_token or "",
    )
    stored_service(
        StoreWriteActionSuccessCommand(
            command_id="store-verify-race",
            request_hash="k1" * 32,
            action_id="action-verify-race",
            attempt_id="attempt-verify-race",
            expected_action_version=2,
            expected_attempt_version=0,
            snapshot=executed.snapshot,
        )
    )
    verify_service = VerifyWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
        gateway=GoogleWorkspaceExecutionBackend(
            gateway=cast(
                GoogleWorkspaceGateway,
                _TransactionCheckingGateway(
                    delegate=fixture_gateway,
                    database_path=write_database,
                    after_get_sql=(
                        "UPDATE actions SET version = version + 1 WHERE id = 'action-verify-race';"
                    ),
                ),
            ),
        ),
    )

    verified = verify_service(
        VerifyWriteActionCommand(
            command_id="verify-race",
            request_hash="k2" * 32,
            action_id="action-verify-race",
            attempt_id="attempt-verify-race",
            expected_action_version=3,
            verification_id="verification-race",
        )
    )

    assert verified.applied is False
    assert verified.result_code == ResultCode.VERSION_CONFLICT.value
    connection = connect_sqlite(write_database)
    try:
        count = connection.execute(
            "SELECT COUNT(*) FROM verifications WHERE id = 'verification-race';"
        ).fetchone()[0]
        receipt = connection.execute(
            """
            SELECT status, result_code
            FROM command_receipts
            WHERE command_id = 'verify-race';
            """
        ).fetchone()
        assert count == 0
        assert tuple(receipt) == ("REJECTED", ResultCode.VERSION_CONFLICT.value)
    finally:
        connection.close()
