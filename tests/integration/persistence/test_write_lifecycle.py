"""Write plan, claim, verification, and transaction tests."""

# ruff: noqa: F401

from __future__ import annotations

from json import loads as _loads

from google_work_agent.application.use_cases.action.write_approval_contracts import (
    DEFAULT_APPROVAL_TTL_MS,
)
from google_work_agent.application.use_cases.plan.publish_plan import PublishPlanHandler
from google_work_agent.application.use_cases.recovery.require_recovery import (
    RequireRecoveryCommand,
    RequireRecoveryHandler,
)
from google_work_agent.application.use_cases.recovery.resolve_recovery import (
    ResolveRecoveryCommandV1,
    ResolveRecoveryHandler,
)
from google_work_agent.domain.recovery.model import RecoveryResolution
from tests.integration.persistence.review_support import record_pass_review
from tests.integration.persistence.test_write_actions import (
    ApproveWriteActionCommand,
    ApproveWriteActionService,
    ClaimWriteActionCommand,
    ClaimWriteActionService,
    EvidenceOriginType,
    ExecuteWriteActionService,
    FakeClockPort,
    FakeGoogleGateway,
    GoogleGatewayFault,
    GoogleGatewayFaultKind,
    GoogleWorkspaceGateway,
    Path,
    PublishWritePlanCommand,
    RequestRunCancellationCommand,
    RequestRunCancellationService,
    ResultCode,
    RunCommand,
    RunStatusV1,
    SaveWritePlanCommand,
    SaveWritePlanService,
    StoreWriteActionSuccessCommand,
    StoreWriteActionSuccessService,
    VerifyWriteActionCommand,
    VerifyWriteActionService,
    WriteActionDraft,
    WriteEvidenceDraft,
    _command_rejected_hash_mismatch_events,
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
from tests.support.resolve_recovery_adapter import (
    RecoveryResolutionKind,
    ResolveMismatchRecoveryCommand,
    ResolveMismatchRecoveryService,
)

pytest_plugins = ("tests.integration.persistence.test_write_actions",)


def test_contract_recovery_recheck_without_new_durable_fact_makes_no_progress(
    write_database: Path,
) -> None:
    clock = FakeClockPort(1_000)
    required = RequireRecoveryHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )(
        RequireRecoveryCommand(
            run_id="run-1",
            expected_version=0,
            command_id="require-recovery-1",
            request_hash="r1" * 32,
            reason="CONTRACT_VIOLATION",
            scope="RUN",
            recovery_fingerprint="checkpoint-mismatch-1",
            contract_or_checkpoint_fingerprint="checkpoint-mismatch-1",
        )
    )
    resolved = ResolveRecoveryHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )(
        ResolveRecoveryCommandV1(
            run_id="run-1",
            expected_version=1,
            command_id="resolve-recovery-1",
            request_hash="r2" * 32,
            recovery_context_version=0,
            resolution=RecoveryResolution.RECHECK,
            target_kind="RUN",
        )
    )

    assert required.applied is True
    assert required.current_status == RunStatusV1.RECOVERY_REQUIRED.value
    assert required.next_allowed_commands == (RunCommand.REQUEST_CANCEL.value,)
    assert resolved.applied is False
    assert resolved.result_code == ResultCode.NO_PROGRESS.value
    assert resolved.current_status == RunStatusV1.RECOVERY_REQUIRED.value
    connection = connect_sqlite(write_database)
    try:
        row = connection.execute("SELECT status, version FROM runs WHERE id = 'run-1';").fetchone()
        assert tuple(row) == ("RECOVERY_REQUIRED", 1)
    finally:
        connection.close()


def test_write_happy_path_requires_approval_then_executes_and_verifies(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClockPort(1000)
    save_service = SaveWritePlanService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )
    publish_service = PublishPlanHandler(
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
                    connector_id="google_workspace",
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
    record_pass_review(write_database, "plan-write-1", now_ms=clock.now_ms())

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
            expected_attempt_version=1,
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
            WHERE id = 'resource-ref-run-1-google_workspace-task-task-created-1';
            """
        ).fetchone()
        attempt_count = connection.execute(
            "SELECT COUNT(*) FROM execution_attempts WHERE approval_id = 'approval-write-1';"
        ).fetchone()[0]

        assert action_row["status"] == "VERIFIED"
        assert action_row["version"] == 4
        assert plan_row["status"] == "WAITING_APPROVAL"
        assert approval_row["status"] == "CONSUMED"
        assert approval_row["consumed_at_ms"] is not None
        assert attempt_row["status"] == "SUCCEEDED"
        assert attempt_row["version"] == 2
        assert attempt_row["result_resource_ref_id"] == (
            "resource-ref-run-1-google_workspace-task-task-created-1"
        )
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
    clock = FakeClockPort(1000)
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
    clock = FakeClockPort(1000)
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
    # Claim expiry is derived from the approval's own expires_at_ms
    # (application/write_claim.py), and approval TTL is now server-owned via
    # AppSettings.approval_ttl_minutes (default 30 minutes -- see
    # DEFAULT_APPROVAL_TTL_MS) rather than the old 30-second default this
    # advance used to target (origin/main still has
    # DEFAULT_APPROVAL_TTL_MS = 30_000). Advance strictly past whatever the
    # real current default is, so this keeps proving genuine expiry
    # rejection instead of silently no-op'ing.
    clock.advance_ms(DEFAULT_APPROVAL_TTL_MS + 1)
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
    clock = FakeClockPort(1000)
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
            expected_attempt_version=1,
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
        connection.execute("UPDATE runs SET status = 'VERIFYING' WHERE id = 'run-1';")
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
        connection.execute("UPDATE runs SET status = 'RECOVERY_REQUIRED' WHERE id = 'run-1';")
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


def test_mismatch_recovery_create_corrective_plan_fails_closed_when_cancel_intent_active(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    run_version = _prepare_mismatch(
        write_database=write_database,
        gateway=fixture_gateway,
        suffix="corrective-cancel",
    )
    cancel_service = RequestRunCancellationService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=lambda: 1500,
    )
    cancelled = cancel_service(
        RequestRunCancellationCommand(
            command_id="cancel-before-corrective",
            request_hash="e1" * 32,
            run_id="run-1",
            expected_run_version=run_version,
        )
    )
    assert cancelled.applied is True

    connection = connect_sqlite(write_database)
    try:
        plan_count_before = connection.execute("SELECT COUNT(*) FROM plans;").fetchone()[0]
        approval_count_before = connection.execute("SELECT COUNT(*) FROM approvals;").fetchone()[0]
    finally:
        connection.close()
    create_task_calls_before = fixture_gateway.count_calls("create_task")

    service = ResolveMismatchRecoveryService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=lambda: 2000,
    )
    result = service(
        ResolveMismatchRecoveryCommand(
            command_id="resolve-corrective-cancel",
            request_hash="e2" * 32,
            run_id="run-1",
            action_id="action-corrective-cancel",
            expected_run_version=cancelled.run_version,
            resolution_kind=RecoveryResolutionKind.CREATE_CORRECTIVE_PLAN,
            corrective_plan_id="plan-corrective-cancel-v2",
        )
    )

    assert result.applied is False
    assert result.result_code == "STATE_CONFLICT"
    connection = connect_sqlite(write_database)
    try:
        plan_count_after = connection.execute("SELECT COUNT(*) FROM plans;").fetchone()[0]
        approval_count_after = connection.execute("SELECT COUNT(*) FROM approvals;").fetchone()[0]
        action_status = connection.execute(
            "SELECT status FROM actions WHERE id = 'action-corrective-cancel';"
        ).fetchone()[0]
    finally:
        connection.close()
    assert plan_count_after == plan_count_before
    assert approval_count_after == approval_count_before
    assert action_status == "MISMATCH"
    assert fixture_gateway.count_calls("create_task") == create_task_calls_before


def test_mismatch_recovery_accept_partial_fails_closed_when_cancel_intent_active(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    run_version = _prepare_mismatch(
        write_database=write_database,
        gateway=fixture_gateway,
        suffix="accept-partial-cancel",
    )
    cancel_service = RequestRunCancellationService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=lambda: 1500,
    )
    cancelled = cancel_service(
        RequestRunCancellationCommand(
            command_id="cancel-before-accept-partial",
            request_hash="e3" * 32,
            run_id="run-1",
            expected_run_version=run_version,
        )
    )
    assert cancelled.applied is True

    service = ResolveMismatchRecoveryService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=lambda: 2000,
    )
    result = service(
        ResolveMismatchRecoveryCommand(
            command_id="resolve-accept-partial-cancel",
            request_hash="e4" * 32,
            run_id="run-1",
            action_id="action-accept-partial-cancel",
            expected_run_version=cancelled.run_version,
            resolution_kind=RecoveryResolutionKind.ACCEPT_PARTIAL,
        )
    )

    assert result.applied is False
    assert result.result_code == "STATE_CONFLICT"
    connection = connect_sqlite(write_database)
    try:
        action_status = connection.execute(
            "SELECT status FROM actions WHERE id = 'action-accept-partial-cancel';"
        ).fetchone()[0]
        run_status = connection.execute("SELECT status FROM runs WHERE id = 'run-1';").fetchone()[0]
    finally:
        connection.close()
    assert action_status == "MISMATCH"
    assert run_status != "COMPLETED"


def test_fail_recovery_transitions_recovery_required_to_failed(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    run_version = _prepare_mismatch(
        write_database=write_database,
        gateway=fixture_gateway,
        suffix="fail-basic",
    )
    service = ResolveMismatchRecoveryService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=lambda: 2000,
    )
    result = service(
        ResolveMismatchRecoveryCommand(
            command_id="resolve-fail-basic",
            request_hash="f1" * 32,
            run_id="run-1",
            action_id="action-fail-basic",
            expected_run_version=run_version,
            resolution_kind=RecoveryResolutionKind.FAIL,
        )
    )

    assert result.applied is True
    assert result.run_status == "FAILED"
    assert result.result_kind == "FAILED"
    connection = connect_sqlite(write_database)
    try:
        row = connection.execute(
            "SELECT status, finished_at_ms FROM runs WHERE id = 'run-1';"
        ).fetchone()
        assert row[0] == "FAILED"
        assert row[1] is not None
    finally:
        connection.close()


def test_fail_recovery_creates_no_new_plan_revision(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    run_version = _prepare_mismatch(
        write_database=write_database,
        gateway=fixture_gateway,
        suffix="fail-plan",
    )
    connection = connect_sqlite(write_database)
    try:
        plans_before = [
            tuple(row) for row in connection.execute("SELECT id, revision_no, status FROM plans;")
        ]
    finally:
        connection.close()

    service = ResolveMismatchRecoveryService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=lambda: 2000,
    )
    result = service(
        ResolveMismatchRecoveryCommand(
            command_id="resolve-fail-plan",
            request_hash="f2" * 32,
            run_id="run-1",
            action_id="action-fail-plan",
            expected_run_version=run_version,
            resolution_kind=RecoveryResolutionKind.FAIL,
        )
    )

    assert result.applied is True
    connection = connect_sqlite(write_database)
    try:
        plans_after = [
            tuple(row) for row in connection.execute("SELECT id, revision_no, status FROM plans;")
        ]
    finally:
        connection.close()
    assert [(row[0], row[1]) for row in plans_after] == [(row[0], row[1]) for row in plans_before]
    assert [row[2] for row in plans_after] == ["CANCELLED"]


def test_fail_recovery_creates_no_new_approval_claim_or_provider_write(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    run_version = _prepare_mismatch(
        write_database=write_database,
        gateway=fixture_gateway,
        suffix="fail-safety",
    )
    connection = connect_sqlite(write_database)
    try:
        counts_before = connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM approvals),
                (SELECT COUNT(*) FROM execution_attempts),
                (SELECT COUNT(*) FROM verifications);
            """
        ).fetchone()
    finally:
        connection.close()
    create_task_calls_before = fixture_gateway.count_calls("create_task")

    service = ResolveMismatchRecoveryService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=lambda: 2000,
    )
    result = service(
        ResolveMismatchRecoveryCommand(
            command_id="resolve-fail-safety",
            request_hash="f3" * 32,
            run_id="run-1",
            action_id="action-fail-safety",
            expected_run_version=run_version,
            resolution_kind=RecoveryResolutionKind.FAIL,
        )
    )

    assert result.applied is True
    connection = connect_sqlite(write_database)
    try:
        counts_after = connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM approvals),
                (SELECT COUNT(*) FROM execution_attempts),
                (SELECT COUNT(*) FROM verifications);
            """
        ).fetchone()
    finally:
        connection.close()
    assert tuple(counts_after) == tuple(counts_before)
    assert fixture_gateway.count_calls("create_task") == create_task_calls_before


def test_fail_recovery_preserves_verified_action_facts_in_partial_run(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    run_version = _prepare_mismatch(
        write_database=write_database,
        gateway=fixture_gateway,
        suffix="fail-partial",
    )
    _insert_action_sibling(
        database_path=write_database,
        source_action_id="action-fail-partial",
        sibling_action_id="action-fail-partial-verified",
        status="VERIFIED",
    )

    service = ResolveMismatchRecoveryService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=lambda: 2000,
    )
    result = service(
        ResolveMismatchRecoveryCommand(
            command_id="resolve-fail-partial",
            request_hash="f4" * 32,
            run_id="run-1",
            action_id="action-fail-partial",
            expected_run_version=run_version,
            resolution_kind=RecoveryResolutionKind.FAIL,
        )
    )

    assert result.applied is True
    assert result.run_status == "FAILED"
    connection = connect_sqlite(write_database)
    try:
        facts = connection.execute(
            """
            SELECT
                (SELECT status FROM actions WHERE id = 'action-fail-partial'),
                (SELECT status FROM actions WHERE id = 'action-fail-partial-verified');
            """
        ).fetchone()
    finally:
        connection.close()
    assert tuple(facts) == ("MISMATCH", "VERIFIED")


def test_fail_recovery_same_command_and_payload_is_idempotent(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    run_version = _prepare_mismatch(
        write_database=write_database,
        gateway=fixture_gateway,
        suffix="fail-idem",
    )
    service = ResolveMismatchRecoveryService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=lambda: 2000,
    )
    command = ResolveMismatchRecoveryCommand(
        command_id="resolve-fail-idem",
        request_hash="f5" * 32,
        run_id="run-1",
        action_id="action-fail-idem",
        expected_run_version=run_version,
        resolution_kind=RecoveryResolutionKind.FAIL,
    )

    first = service(command)
    second = service(command)

    assert first.applied is True
    assert second.applied is True
    assert second.run_status == "FAILED"
    assert second.run_version == first.run_version
    connection = connect_sqlite(write_database)
    try:
        run_row = connection.execute(
            "SELECT status, version FROM runs WHERE id = 'run-1';"
        ).fetchone()
    finally:
        connection.close()
    assert tuple(run_row) == ("FAILED", first.run_version)


def test_fail_recovery_same_command_different_payload_is_fail_closed(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    run_version = _prepare_mismatch(
        write_database=write_database,
        gateway=fixture_gateway,
        suffix="fail-conflict",
    )
    service = ResolveMismatchRecoveryService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=lambda: 2000,
    )
    first = service(
        ResolveMismatchRecoveryCommand(
            command_id="resolve-fail-conflict",
            request_hash="f6" * 32,
            run_id="run-1",
            action_id="action-fail-conflict",
            expected_run_version=run_version,
            resolution_kind=RecoveryResolutionKind.FAIL,
        )
    )
    assert first.applied is True

    second = service(
        ResolveMismatchRecoveryCommand(
            command_id="resolve-fail-conflict",
            request_hash="f7" * 32,
            run_id="run-1",
            action_id="action-fail-conflict",
            expected_run_version=run_version,
            resolution_kind=RecoveryResolutionKind.FAIL,
        )
    )

    assert second.applied is False
    assert second.result_code == "DUPLICATE_COMMAND"
    connection = connect_sqlite(write_database)
    try:
        run_row = connection.execute(
            "SELECT status, version FROM runs WHERE id = 'run-1';"
        ).fetchone()
    finally:
        connection.close()
    assert tuple(run_row) == ("FAILED", first.run_version)


def test_fail_recovery_terminal_blocks_accept_partial_and_corrective_replan(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    run_version = _prepare_mismatch(
        write_database=write_database,
        gateway=fixture_gateway,
        suffix="fail-terminal",
    )
    service = ResolveMismatchRecoveryService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=lambda: 2000,
    )
    failed = service(
        ResolveMismatchRecoveryCommand(
            command_id="resolve-fail-terminal",
            request_hash="f8" * 32,
            run_id="run-1",
            action_id="action-fail-terminal",
            expected_run_version=run_version,
            resolution_kind=RecoveryResolutionKind.FAIL,
        )
    )
    assert failed.applied is True
    assert failed.run_status == "FAILED"

    accept_partial = service(
        ResolveMismatchRecoveryCommand(
            command_id="resolve-fail-terminal-accept-partial",
            request_hash="f9" * 32,
            run_id="run-1",
            action_id="action-fail-terminal",
            expected_run_version=failed.run_version,
            resolution_kind=RecoveryResolutionKind.ACCEPT_PARTIAL,
        )
    )
    corrective = service(
        ResolveMismatchRecoveryCommand(
            command_id="resolve-fail-terminal-corrective",
            request_hash="fa" * 32,
            run_id="run-1",
            action_id="action-fail-terminal",
            expected_run_version=failed.run_version,
            resolution_kind=RecoveryResolutionKind.CREATE_CORRECTIVE_PLAN,
            corrective_plan_id="plan-fail-terminal-v2",
        )
    )

    assert accept_partial.applied is False
    assert corrective.applied is False
    connection = connect_sqlite(write_database)
    try:
        run_status = connection.execute("SELECT status FROM runs WHERE id = 'run-1';").fetchone()[0]
    finally:
        connection.close()
    assert run_status == "FAILED"


def test_fail_recovery_fails_closed_when_cancel_intent_active(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    run_version = _prepare_mismatch(
        write_database=write_database,
        gateway=fixture_gateway,
        suffix="fail-cancel",
    )
    cancel_service = RequestRunCancellationService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=lambda: 1500,
    )
    cancelled = cancel_service(
        RequestRunCancellationCommand(
            command_id="cancel-before-fail",
            request_hash="fb" * 32,
            run_id="run-1",
            expected_run_version=run_version,
        )
    )
    assert cancelled.applied is True

    service = ResolveMismatchRecoveryService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=lambda: 2000,
    )
    result = service(
        ResolveMismatchRecoveryCommand(
            command_id="resolve-fail-cancel",
            request_hash="fc" * 32,
            run_id="run-1",
            action_id="action-fail-cancel",
            expected_run_version=cancelled.run_version,
            resolution_kind=RecoveryResolutionKind.FAIL,
        )
    )

    assert result.applied is False
    assert result.result_code == "STATE_CONFLICT"
    connection = connect_sqlite(write_database)
    try:
        run_status = connection.execute("SELECT status FROM runs WHERE id = 'run-1';").fetchone()[0]
    finally:
        connection.close()
    assert run_status != "FAILED"


def test_verify_write_action_get_runs_without_sqlite_write_transaction(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClockPort(1000)
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
            expected_attempt_version=1,
            snapshot=executed.snapshot,
        )
    )
    verify_service = VerifyWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
        gateway=cast(
            GoogleWorkspaceGateway,
            _TransactionCheckingGateway(
                delegate=fixture_gateway,
                database_path=write_database,
            ),
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
    clock = FakeClockPort(1000)
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
            expected_attempt_version=1,
            snapshot=executed.snapshot,
        )
    )
    verify_service = VerifyWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
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


def test_claim_hash_mismatch_emits_exactly_one_rejection_audit_event(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClockPort(1000)
    _prepare_write_plan(write_database=write_database, clock=clock, suffix="claim-reject")
    ApproveWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )(
        ApproveWriteActionCommand(
            command_id="approve-claim-reject",
            request_hash="a1" * 32,
            action_id="action-claim-reject",
            expected_version=0,
            approved_by_account_id="account-1",
            approved_by_display="User",
            source_snapshot={},
            approval_id="approval-claim-reject",
            idempotency_key="a2" * 32,
        )
    )
    claim_service = ClaimWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
        signing_secret="phase-e-secret",
        service_instance_id="write-svc-1",
    )
    command = ClaimWriteActionCommand(
        command_id="claim-reject-command",
        request_hash="a3" * 32,
        action_id="action-claim-reject",
        expected_version=1,
        source_snapshot={},
        attempt_id="attempt-claim-reject",
        nonce="nonce-claim-reject",
    )
    first = claim_service(command)
    replay = claim_service(command)

    assert first == replay
    # B: a same-hash idempotent replay is not a rejection.
    assert _command_rejected_hash_mismatch_events(write_database) == ()

    hash_conflict = claim_service(
        ClaimWriteActionCommand(
            command_id=command.command_id,
            request_hash="a4" * 32,
            action_id=command.action_id,
            expected_version=command.expected_version,
            source_snapshot={},
            attempt_id=command.attempt_id,
            nonce=command.nonce,
        )
    )

    assert hash_conflict.result_code == ResultCode.DUPLICATE_COMMAND.value

    # A: exactly one rejection event, action-scoped (no run_id available
    # without an extra lookup, so audit fires with run_id=None -- trace is
    # skipped since trace_events.run_id is NOT NULL).
    rejection_events = _command_rejected_hash_mismatch_events(write_database)
    assert len(rejection_events) == 1
    envelope, outcome = rejection_events[0]
    assert outcome == ResultCode.DUPLICATE_COMMAND.value
    assert envelope["attributes"] == {
        "command_id": command.command_id,
        "command_type": "ClaimWriteAction",
        "result_code": ResultCode.DUPLICATE_COMMAND.value,
    }
    assert envelope["correlation"]["run_id"] is None
    assert envelope["correlation"]["action_id"] == command.action_id
    raw = str(envelope)
    assert "nonce" not in raw
    assert "claim_token" not in raw.lower()
    assert "secret" not in raw.lower()
