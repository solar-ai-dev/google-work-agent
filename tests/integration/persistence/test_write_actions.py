import sqlite3
from collections.abc import Mapping
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
    ExecuteWriteActionService,
    FinalizeRunCancellationCommand,
    FinalizeRunCancellationService,
    MarkWriteActionUnknownResultCommand,
    MarkWriteActionUnknownResultService,
    PreflightWriteActionService,
    PrepareWriteRetryCommand,
    PrepareWriteRetryService,
    PublishWritePlanCommand,
    PublishWritePlanService,
    RecoverUnknownCreateActionCommand,
    RecoverUnknownCreateActionService,
    RecoverUnknownDeleteActionCommand,
    RecoverUnknownDeleteActionService,
    RecoverUnknownSendActionCommand,
    RecoverUnknownSendActionService,
    RecoverUnknownUpdateActionCommand,
    RecoverUnknownUpdateActionService,
    RecoveryResolutionKind,
    RequestRunCancellationCommand,
    RequestRunCancellationService,
    RequireWriteReauthCommand,
    RequireWriteReauthService,
    ResolveMismatchRecoveryCommand,
    ResolveMismatchRecoveryService,
    SaveWritePlanCommand,
    SaveWritePlanService,
    StoreWriteActionSuccessCommand,
    StoreWriteActionSuccessService,
    VerifyWriteActionCommand,
    VerifyWriteActionService,
    WriteActionDraft,
    WriteActionResponse,
    WriteEvidenceDraft,
)
from google_work_agent.application.write_actions import (
    DeliveryCertainty,
    classify_write_delivery,
    is_reauth_required_error,
)
from google_work_agent.domain import PolicyViolationError, ResultCode, RunCommand, RunStatus
from google_work_agent.ports import (
    EvidenceOriginType,
    GoogleWorkspaceErrorCode,
    GoogleWorkspaceGatewayError,
    ResourceSnapshot,
)
from tests.support.fakes import (
    FakeClock,
    FakeGoogleGateway,
    GoogleGatewayFault,
    GoogleGatewayFaultKind,
)
from tests.support.fixtures import ProductFixtureSnapshotLoader

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "product"


@pytest.fixture()
def write_database(tmp_path: Path) -> Path:
    database_path = tmp_path / "write-actions.db"
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


@pytest.fixture()
def fixture_gateway() -> FakeGoogleGateway:
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    return FakeGoogleGateway(snapshot)


class _TransactionCheckingGateway:
    def __init__(
        self,
        *,
        delegate: FakeGoogleGateway,
        database_path: Path,
        after_get_sql: str | None = None,
    ) -> None:
        self._delegate = delegate
        self._database_path = database_path
        self._after_get_sql = after_get_sql

    def get_task(self, *, task_list_id: str, task_id: str) -> ResourceSnapshot:
        _assert_can_open_sqlite_write_transaction(self._database_path)
        snapshot = self._delegate.get_task(task_list_id=task_list_id, task_id=task_id)
        if self._after_get_sql is not None:
            connection = connect_sqlite(self._database_path)
            try:
                connection.execute(self._after_get_sql)
                connection.commit()
            finally:
                connection.close()
        return snapshot

    def get_gmail_message(self, *, message_id: str) -> ResourceSnapshot:
        _assert_can_open_sqlite_write_transaction(self._database_path)
        return self._delegate.get_gmail_message(message_id=message_id)

    def get_gmail_draft(self, *, draft_id: str) -> ResourceSnapshot:
        _assert_can_open_sqlite_write_transaction(self._database_path)
        return self._delegate.get_gmail_draft(draft_id=draft_id)

    def get_calendar_event(self, *, calendar_id: str, event_id: str) -> ResourceSnapshot:
        _assert_can_open_sqlite_write_transaction(self._database_path)
        return self._delegate.get_calendar_event(calendar_id=calendar_id, event_id=event_id)


def _assert_can_open_sqlite_write_transaction(database_path: Path) -> None:
    connection = sqlite3.connect(database_path, timeout=0, isolation_level=None)
    try:
        connection.execute("BEGIN IMMEDIATE;")
        connection.execute("ROLLBACK;")
    finally:
        connection.close()


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
        assert [tuple(row) for row in plans] == [
            ("plan-corrective", 1, "SUPERSEDED"),
            ("plan-corrective-v2", 2, "DRAFT"),
        ]
        assert tuple(counts) == (1, 1, 1, 1)
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
        gateway=_TransactionCheckingGateway(
            delegate=fixture_gateway,
            database_path=write_database,
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
        gateway=_TransactionCheckingGateway(
            delegate=fixture_gateway,
            database_path=write_database,
            after_get_sql=(
                "UPDATE actions SET version = version + 1 WHERE id = 'action-verify-race';"
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


def test_delivery_certainty_and_reauth_classification_are_pure() -> None:
    not_sent = GoogleWorkspaceGatewayError(
        code=GoogleWorkspaceErrorCode.TIMEOUT,
        message="timeout before delivery",
        delivered=False,
        mutated=False,
    )
    uncertain = GoogleWorkspaceGatewayError(
        code=GoogleWorkspaceErrorCode.TIMEOUT,
        message="timeout after delivery",
        delivered=True,
        mutated=False,
    )
    response_lost = GoogleWorkspaceGatewayError(
        code=GoogleWorkspaceErrorCode.AUTH_EXPIRED,
        message="auth expired after mutation",
        delivered=True,
        mutated=True,
    )

    assert classify_write_delivery(not_sent) is DeliveryCertainty.NOT_SENT
    assert classify_write_delivery(uncertain) is DeliveryCertainty.MAY_HAVE_BEEN_SENT
    assert classify_write_delivery(response_lost) is DeliveryCertainty.SENT_RESPONSE_LOST
    assert is_reauth_required_error(not_sent) is False
    assert is_reauth_required_error(response_lost) is True


def test_gmail_send_uses_approval_claim_sent_lookup_and_verification(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClock(1000)
    _prepare_effect_write_plan(
        write_database=write_database,
        clock=clock,
        suffix="send",
        tool_name="gmail_send",
        arguments={"draft_id": "draft-followup"},
        expected={
            "resource_type": "gmail_message",
            "resource_id": "sent-draft-followup",
            "parent_id": "thread-project",
            "version": "1",
            "payload": {
                "thread_id": "thread-project",
                "to": ["pm@example.com"],
                "subject": "Re: Project sync follow-up",
                "body": "Draft summary is ready for review.",
                "draft_id": "draft-followup",
                "sent": True,
                "resource_id": "sent-draft-followup",
            },
        },
    )
    approved = _approve_effect_action(
        write_database=write_database,
        clock=clock,
        suffix="send",
    )
    PreflightWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        gateway=fixture_gateway,
    )(action_id="action-send")
    claimed = _claim_effect_action(
        write_database=write_database,
        clock=clock,
        suffix="send",
        expected_version=approved.action_version,
    )
    executed = ExecuteWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        gateway=fixture_gateway,
        now_ms=clock.now_ms,
        signing_secret="phase-e-secret",
        service_instance_id="write-svc-1",
    )(action_id="action-send", claim_token=claimed.claim_token or "")
    stored = StoreWriteActionSuccessService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )(
        StoreWriteActionSuccessCommand(
            command_id="store-send",
            request_hash="s1" * 32,
            action_id="action-send",
            attempt_id="attempt-send",
            expected_action_version=claimed.action_version,
            expected_attempt_version=0,
            snapshot=executed.snapshot,
        )
    )
    verified = VerifyWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
        gateway=fixture_gateway,
    )(
        VerifyWriteActionCommand(
            command_id="verify-send",
            request_hash="s2" * 32,
            action_id="action-send",
            attempt_id="attempt-send",
            expected_action_version=stored.action_version,
            verification_id="verification-send",
        )
    )

    assert verified.action_status == "VERIFIED"
    assert fixture_gateway.count_calls("send_gmail") == 1
    assert fixture_gateway.count_calls("get_gmail_message") == 1


def test_calendar_delete_uses_preflight_claim_get_absent_and_verification(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClock(1000)
    _insert_calendar_event_reference(write_database)
    _prepare_effect_write_plan(
        write_database=write_database,
        clock=clock,
        suffix="delete",
        tool_name="calendar_delete_event",
        arguments={"calendar_id": "calendar-primary", "event_id": "event-focus"},
        expected={"resource_type": "calendar_event", "resource_id": "event-focus", "absent": True},
        target_resource_ref_id="resource-event-focus",
    )
    approved = _approve_effect_action(
        write_database=write_database,
        clock=clock,
        suffix="delete",
    )
    PreflightWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        gateway=fixture_gateway,
    )(action_id="action-delete")
    claimed = _claim_effect_action(
        write_database=write_database,
        clock=clock,
        suffix="delete",
        expected_version=approved.action_version,
    )
    executed = ExecuteWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        gateway=fixture_gateway,
        now_ms=clock.now_ms,
        signing_secret="phase-e-secret",
        service_instance_id="write-svc-1",
    )(action_id="action-delete", claim_token=claimed.claim_token or "")
    stored = StoreWriteActionSuccessService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )(
        StoreWriteActionSuccessCommand(
            command_id="store-delete",
            request_hash="d1" * 32,
            action_id="action-delete",
            attempt_id="attempt-delete",
            expected_action_version=claimed.action_version,
            expected_attempt_version=0,
            snapshot=executed.snapshot,
        )
    )
    verified = VerifyWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
        gateway=fixture_gateway,
    )(
        VerifyWriteActionCommand(
            command_id="verify-delete",
            request_hash="d2" * 32,
            action_id="action-delete",
            attempt_id="attempt-delete",
            expected_action_version=stored.action_version,
            verification_id="verification-delete",
        )
    )

    assert verified.action_status == "VERIFIED"
    assert fixture_gateway.count_calls("delete_calendar_event") == 1
    assert fixture_gateway.count_calls("get_calendar_event") == 1


def test_calendar_delete_preflight_rejects_recurring_series_scope(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClock(1000)
    _insert_calendar_event_reference(write_database)
    _prepare_effect_write_plan(
        write_database=write_database,
        clock=clock,
        suffix="delete-series",
        tool_name="calendar_delete_event",
        arguments={
            "calendar_id": "calendar-primary",
            "event_id": "event-focus",
            "delete_scope": "SERIES",
        },
        expected={"resource_type": "calendar_event", "resource_id": "event-focus", "absent": True},
        target_resource_ref_id="resource-event-focus",
    )
    _approve_effect_action(write_database=write_database, clock=clock, suffix="delete-series")

    with pytest.raises(PolicyViolationError, match="recurring series deletion"):
        PreflightWriteActionService(
            unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
            gateway=fixture_gateway,
        )(action_id="action-delete-series")

    assert fixture_gateway.count_calls("delete_calendar_event") == 0


def test_calendar_delete_preflight_rejects_target_version_change(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClock(1000)
    _insert_calendar_event_reference(write_database, version="6")
    _prepare_effect_write_plan(
        write_database=write_database,
        clock=clock,
        suffix="delete-stale",
        tool_name="calendar_delete_event",
        arguments={"calendar_id": "calendar-primary", "event_id": "event-focus"},
        expected={"resource_type": "calendar_event", "resource_id": "event-focus", "absent": True},
        target_resource_ref_id="resource-event-focus",
    )
    _approve_effect_action(write_database=write_database, clock=clock, suffix="delete-stale")

    with pytest.raises(PolicyViolationError, match="target version mismatch"):
        PreflightWriteActionService(
            unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
            gateway=fixture_gateway,
        )(action_id="action-delete-stale")

    assert fixture_gateway.count_calls("delete_calendar_event") == 0


def test_unknown_gmail_send_recovers_by_fingerprint_without_resending(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClock(1000)
    _prepare_effect_write_plan(
        write_database=write_database,
        clock=clock,
        suffix="recover-send",
        tool_name="gmail_send",
        arguments={"draft_id": "draft-followup"},
        expected={},
    )
    approved = _approve_effect_action(
        write_database=write_database, clock=clock, suffix="recover-send"
    )
    claimed = _claim_effect_action(
        write_database=write_database,
        clock=clock,
        suffix="recover-send",
        expected_version=approved.action_version,
    )
    fixture_gateway.queue_fault(
        operation="send_gmail",
        fault=GoogleGatewayFault(GoogleGatewayFaultKind.HTTP_500),
    )
    execute_service = ExecuteWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        gateway=fixture_gateway,
        now_ms=clock.now_ms,
        signing_secret="phase-e-secret",
        service_instance_id="write-svc-1",
    )

    with pytest.raises(GoogleWorkspaceGatewayError) as error_info:
        execute_service(
            action_id="action-recover-send",
            claim_token=claimed.claim_token or "",
        )
    assert classify_write_delivery(error_info.value) is DeliveryCertainty.SENT_RESPONSE_LOST
    _mark_effect_unknown(
        write_database=write_database,
        clock=clock,
        suffix="recover-send",
        error=error_info.value,
    )

    recovered = RecoverUnknownSendActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
        gateway=fixture_gateway,
    )(
        RecoverUnknownSendActionCommand(
            command_id="recover-send-1",
            request_hash="e0" * 32,
            action_id="action-recover-send",
            attempt_id="attempt-recover-send",
            expected_action_version=3,
            expected_attempt_version=1,
        )
    )

    assert recovered.action_status == "EXECUTED"
    assert fixture_gateway.count_calls("send_gmail") == 1
    assert fixture_gateway.count_calls("search_by_recovery_fingerprint") == 1


def test_unknown_calendar_delete_recovers_from_target_absence_without_redelete(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClock(1000)
    _insert_calendar_event_reference(write_database)
    _prepare_effect_write_plan(
        write_database=write_database,
        clock=clock,
        suffix="recover-delete",
        tool_name="calendar_delete_event",
        arguments={"calendar_id": "calendar-primary", "event_id": "event-focus"},
        expected={"resource_type": "calendar_event", "resource_id": "event-focus", "absent": True},
        target_resource_ref_id="resource-event-focus",
    )
    approved = _approve_effect_action(
        write_database=write_database,
        clock=clock,
        suffix="recover-delete",
    )
    claimed = _claim_effect_action(
        write_database=write_database,
        clock=clock,
        suffix="recover-delete",
        expected_version=approved.action_version,
    )
    fixture_gateway.queue_fault(
        operation="delete_calendar_event",
        fault=GoogleGatewayFault(GoogleGatewayFaultKind.TIMEOUT_AFTER_DELIVERY),
    )
    execute_service = ExecuteWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        gateway=fixture_gateway,
        now_ms=clock.now_ms,
        signing_secret="phase-e-secret",
        service_instance_id="write-svc-1",
    )

    with pytest.raises(GoogleWorkspaceGatewayError) as error_info:
        execute_service(
            action_id="action-recover-delete",
            claim_token=claimed.claim_token or "",
        )
    _mark_effect_unknown(
        write_database=write_database,
        clock=clock,
        suffix="recover-delete",
        error=error_info.value,
    )

    recovered = RecoverUnknownDeleteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
        gateway=fixture_gateway,
    )(
        RecoverUnknownDeleteActionCommand(
            command_id="recover-delete-1",
            request_hash="f0" * 32,
            action_id="action-recover-delete",
            attempt_id="attempt-recover-delete",
            expected_action_version=3,
            expected_attempt_version=1,
        )
    )

    assert recovered.action_status == "EXECUTED"
    assert fixture_gateway.count_calls("delete_calendar_event") == 1


def test_unknown_calendar_delete_with_present_target_requires_reapproval_not_redelete(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClock(1000)
    _insert_calendar_event_reference(write_database)
    _prepare_effect_write_plan(
        write_database=write_database,
        clock=clock,
        suffix="recover-delete-present",
        tool_name="calendar_delete_event",
        arguments={"calendar_id": "calendar-primary", "event_id": "event-focus"},
        expected={"resource_type": "calendar_event", "resource_id": "event-focus", "absent": True},
        target_resource_ref_id="resource-event-focus",
    )
    approved = _approve_effect_action(
        write_database=write_database,
        clock=clock,
        suffix="recover-delete-present",
    )
    _claim_effect_action(
        write_database=write_database,
        clock=clock,
        suffix="recover-delete-present",
        expected_version=approved.action_version,
    )
    _mark_effect_unknown(
        write_database=write_database,
        clock=clock,
        suffix="recover-delete-present",
        error=GoogleWorkspaceGatewayError(
            code=GoogleWorkspaceErrorCode.TIMEOUT,
            message="delivery uncertain",
            delivered=True,
            mutated=False,
        ),
    )

    recovered = RecoverUnknownDeleteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
        gateway=fixture_gateway,
    )(
        RecoverUnknownDeleteActionCommand(
            command_id="recover-delete-present-1",
            request_hash="f1" * 32,
            action_id="action-recover-delete-present",
            attempt_id="attempt-recover-delete-present",
            expected_action_version=3,
            expected_attempt_version=1,
        )
    )

    assert recovered.result_code == ResultCode.RECOVERY_REQUIRED.value
    assert fixture_gateway.count_calls("delete_calendar_event") == 0


def test_unknown_result_create_recovery_and_retry_flow(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClock(1000)
    claimed = _prepare_claimed_action(
        write_database=write_database,
        clock=clock,
        suffix="recover-create",
    )
    execute_service = ExecuteWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        gateway=fixture_gateway,
        now_ms=clock.now_ms,
        signing_secret="phase-e-secret",
        service_instance_id="write-svc-1",
    )
    fixture_gateway.queue_fault(
        operation="create_task",
        fault=GoogleGatewayFault(GoogleGatewayFaultKind.TIMEOUT_AFTER_DELIVERY),
    )

    with pytest.raises(GoogleWorkspaceGatewayError) as error_info:
        execute_service(
            action_id="action-recover-create",
            claim_token=claimed.claim_token or "",
        )
    assert classify_write_delivery(error_info.value) is DeliveryCertainty.SENT_RESPONSE_LOST

    unknown_service = MarkWriteActionUnknownResultService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )
    unknown = unknown_service(
        MarkWriteActionUnknownResultCommand(
            command_id="unknown-create-1",
            request_hash="u1" * 32,
            action_id="action-recover-create",
            attempt_id="attempt-recover-create",
            expected_action_version=2,
            expected_attempt_version=0,
            error_code=error_info.value.code.value,
            error_detail=str(error_info.value),
        )
    )
    assert unknown.applied is True
    assert unknown.action_status == "UNKNOWN_RESULT"

    recover_service = RecoverUnknownCreateActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
        gateway=fixture_gateway,
    )
    recovered = recover_service(
        RecoverUnknownCreateActionCommand(
            command_id="recover-create-1",
            request_hash="u2" * 32,
            action_id="action-recover-create",
            attempt_id="attempt-recover-create",
            expected_action_version=3,
            expected_attempt_version=1,
        )
    )
    assert recovered.applied is True
    assert recovered.action_status == "EXECUTED"

    connection = connect_sqlite(write_database)
    try:
        rows = connection.execute(
            """
            SELECT
                (SELECT status FROM runs WHERE id = 'run-1') AS run_status,
                (SELECT status FROM actions WHERE id = 'action-recover-create') AS action_status,
                (
                    SELECT status
                    FROM execution_attempts
                    WHERE id = 'attempt-recover-create'
                ) AS attempt_status;
            """
        ).fetchone()
        assert tuple(rows) == ("VERIFYING", "EXECUTED", "SUCCEEDED")
    finally:
        connection.close()


def test_update_recovery_can_resolve_unknown_as_failed_when_source_is_unchanged(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClock(1000)
    _prepare_update_claimed_action(write_database=write_database, clock=clock, suffix="update")

    unknown_service = MarkWriteActionUnknownResultService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )
    unknown_service(
        MarkWriteActionUnknownResultCommand(
            command_id="unknown-update-1",
            request_hash="v1" * 32,
            action_id="action-update",
            attempt_id="attempt-update",
            expected_action_version=2,
            expected_attempt_version=0,
            error_code=GoogleWorkspaceErrorCode.TIMEOUT.value,
            error_detail="timeout after delivery",
        )
    )

    recover_service = RecoverUnknownUpdateActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
        gateway=fixture_gateway,
    )
    resolved = recover_service(
        RecoverUnknownUpdateActionCommand(
            command_id="recover-update-1",
            request_hash="v2" * 32,
            action_id="action-update",
            attempt_id="attempt-update",
            expected_action_version=3,
            expected_attempt_version=1,
        )
    )
    assert resolved.applied is True
    assert resolved.action_status == "FAILED"

    retry_service = PrepareWriteRetryService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )
    retried = retry_service(
        PrepareWriteRetryCommand(
            command_id="retry-update-1",
            request_hash="v3" * 32,
            action_id="action-update",
            expected_action_version=4,
        )
    )
    assert retried.applied is True
    assert retried.action_status == "MODIFIED"


def test_update_recovery_get_runs_without_sqlite_write_transaction(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClock(1000)
    _prepare_update_claimed_action(
        write_database=write_database,
        clock=clock,
        suffix="boundary-update",
    )
    unknown_service = MarkWriteActionUnknownResultService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )
    unknown_service(
        MarkWriteActionUnknownResultCommand(
            command_id="unknown-boundary-update",
            request_hash="l1" * 32,
            action_id="action-boundary-update",
            attempt_id="attempt-boundary-update",
            expected_action_version=2,
            expected_attempt_version=0,
            error_code=GoogleWorkspaceErrorCode.TIMEOUT.value,
            error_detail="timeout after delivery",
        )
    )
    recover_service = RecoverUnknownUpdateActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
        gateway=_TransactionCheckingGateway(
            delegate=fixture_gateway,
            database_path=write_database,
        ),
    )

    resolved = recover_service(
        RecoverUnknownUpdateActionCommand(
            command_id="recover-boundary-update",
            request_hash="l2" * 32,
            action_id="action-boundary-update",
            attempt_id="attempt-boundary-update",
            expected_action_version=3,
            expected_attempt_version=1,
        )
    )

    assert resolved.applied is True
    assert resolved.action_status == "FAILED"


def test_waiting_approval_cancel_revokes_approval_and_finalizes_cancelled(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    del fixture_gateway
    clock = FakeClock(1000)
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
    clock = FakeClock(1000)
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
    hash_conflict = service(
        RequestRunCancellationCommand(
            command_id=command.command_id,
            request_hash="f9" * 32,
            run_id=command.run_id,
            expected_run_version=command.expected_run_version,
        )
    )

    assert first == replay
    assert hash_conflict.result_code == ResultCode.DUPLICATE_COMMAND.value
    assert _cancel_child_snapshot(write_database) == snapshot


def test_executing_cancel_waits_for_external_result_without_new_attempt(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClock(1000)
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
    assert blocked_claim.conflict_detail == "run status forbids a new write claim"
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
    clock = FakeClock(1000)
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
    assert finalized.result_kind == "PARTIAL"
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
    clock = FakeClock(1000)
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
    finally:
        connection.close()


def test_unknown_result_cancel_enters_recovery_without_blind_retry(
    write_database: Path,
) -> None:
    clock = FakeClock(1000)
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
    connection = connect_sqlite(write_database)
    try:
        counts = connection.execute(
            "SELECT COUNT(*), COUNT(DISTINCT id) FROM execution_attempts;"
        ).fetchone()
        assert tuple(counts) == (1, 1)
    finally:
        connection.close()


def _cancel_child_snapshot(database_path: Path) -> tuple[object, ...]:
    connection = connect_sqlite(database_path)
    try:
        row = connection.execute(
            """
            SELECT
                (SELECT status FROM runs WHERE id = 'run-1'),
                (SELECT version FROM runs WHERE id = 'run-1'),
                (SELECT status FROM plans WHERE id = 'plan-atomic-cancel'),
                (SELECT status FROM actions WHERE id = 'action-atomic-cancel'),
                (SELECT version FROM actions WHERE id = 'action-atomic-cancel'),
                (SELECT status FROM approvals WHERE id = 'approval-atomic-cancel');
            """
        ).fetchone()
        return tuple(row)
    finally:
        connection.close()


def _run_version(database_path: Path) -> int:
    connection = connect_sqlite(database_path)
    try:
        row = connection.execute("SELECT version FROM runs WHERE id = 'run-1';").fetchone()
        return int(row[0])
    finally:
        connection.close()


def test_reauth_core_command_marks_run_without_langgraph_dependency(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    del fixture_gateway
    clock = FakeClock(1000)
    _prepare_write_plan(write_database=write_database, clock=clock, suffix="reauth")
    request_service = RequireWriteReauthService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )
    response = request_service(
        RequireWriteReauthCommand(
            command_id="reauth-1",
            request_hash="z1" * 32,
            run_id="run-1",
            action_id="action-reauth",
            safe_error_code=GoogleWorkspaceErrorCode.AUTH_EXPIRED.value,
        )
    )
    assert response.applied is True
    assert response.run_status == "REAUTH_REQUIRED"


def _prepare_write_plan(
    *, write_database: Path, clock: FakeClock, suffix: str, run_id: str = "run-1"
) -> None:
    if run_id != "run-1":
        connection = connect_sqlite(write_database)
        try:
            connection.execute(
                """
                INSERT INTO conversations (id, account_id, title, created_at_ms, updated_at_ms)
                VALUES (?, 'account-1', ?, 1, 1);
                """,
                (f"conversation-{suffix}", f"Conversation {suffix}"),
            )
            connection.execute(
                """
                INSERT INTO runs (
                    id, conversation_id, entry_mode, status, langgraph_thread_id,
                    requested_mode, budget_json, version, started_at_ms
                )
                VALUES (?, ?, 'AGENT_SEARCH', 'PLANNING', ?, 'AUTO', '{}', 0, 100);
                """,
                (run_id, f"conversation-{suffix}", f"thread-{suffix}"),
            )
        finally:
            connection.close()

    save_service = SaveWritePlanService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )
    publish_service = PublishWritePlanService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )
    payload = {
        "resource_id": f"task-{suffix}",
        "title": f"title-{suffix}",
        "status": "needsAction",
    }
    expected = _expected_task_projection(
        resource_id=f"task-{suffix}",
        payload=payload,
        version="1",
    )
    save_service(
        SaveWritePlanCommand(
            command_id=f"save-{suffix}",
            request_hash=("d" + suffix[0]) * 32,
            plan_id=f"plan-{suffix}",
            run_id=run_id,
            revision_no=1,
            summary_text="prepare write plan",
            expected_run_version=0,
            actions=(
                WriteActionDraft(
                    action_id=f"action-{suffix}",
                    position=1,
                    tool_name="tasks_create_task",
                    arguments={"task_list_id": "task-list-default", "payload": payload},
                    expected=expected,
                    evidence_ids=(f"evidence-{suffix}",),
                ),
            ),
            evidence=(
                WriteEvidenceDraft(
                    evidence_id=f"evidence-{suffix}",
                    origin_type=EvidenceOriginType.DERIVED,
                    kind="USER_REQUEST",
                    excerpt="prepare write plan",
                ),
            ),
        )
    )
    publish_service(
        PublishWritePlanCommand(
            command_id=f"publish-{suffix}",
            request_hash=("e" + suffix[0]) * 32,
            plan_id=f"plan-{suffix}",
            run_id=run_id,
            expected_run_version=0,
        )
    )


def _prepare_claimed_action(
    *,
    write_database: Path,
    clock: FakeClock,
    suffix: str,
    run_id: str = "run-1",
) -> WriteActionResponse:
    _prepare_write_plan(write_database=write_database, clock=clock, suffix=suffix, run_id=run_id)
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
    approve_service(
        ApproveWriteActionCommand(
            command_id=f"approve-{suffix}",
            request_hash=("f" + suffix[0]) * 32,
            action_id=f"action-{suffix}",
            expected_version=0,
            approved_by_account_id="account-1",
            approved_by_display="User",
            source_snapshot={},
            approval_id=f"approval-{suffix}",
            idempotency_key=(f"approve-{suffix}".encode().hex())[:64].ljust(64, "0"),
        )
    )
    return claim_service(
        ClaimWriteActionCommand(
            command_id=f"claim-{suffix}",
            request_hash=("g" + suffix[0]) * 32,
            action_id=f"action-{suffix}",
            expected_version=1,
            source_snapshot={},
            attempt_id=f"attempt-{suffix}",
            nonce=f"nonce-{suffix}",
        )
    )


def _prepare_mismatch(*, write_database: Path, gateway: FakeGoogleGateway, suffix: str) -> int:
    clock = FakeClock(1000)
    claimed = _prepare_claimed_action(
        write_database=write_database,
        clock=clock,
        suffix=suffix,
    )
    execute_service = ExecuteWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        gateway=gateway,
        now_ms=clock.now_ms,
        signing_secret="phase-e-secret",
        service_instance_id="write-svc-1",
    )
    store_service = StoreWriteActionSuccessService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )
    verify_service = VerifyWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
        gateway=gateway,
    )
    executed = execute_service(
        action_id=f"action-{suffix}",
        claim_token=claimed.claim_token or "",
    )
    store_service(
        StoreWriteActionSuccessCommand(
            command_id=f"store-{suffix}",
            request_hash="c8" * 32,
            action_id=f"action-{suffix}",
            attempt_id=f"attempt-{suffix}",
            expected_action_version=2,
            expected_attempt_version=0,
            snapshot=executed.snapshot,
        )
    )
    gateway.queue_fault(
        operation="get_task",
        fault=GoogleGatewayFault(GoogleGatewayFaultKind.VERIFICATION_MISMATCH),
    )
    verify_service(
        VerifyWriteActionCommand(
            command_id=f"verify-{suffix}",
            request_hash="c9" * 32,
            action_id=f"action-{suffix}",
            attempt_id=f"attempt-{suffix}",
            expected_action_version=3,
            verification_id=f"verification-{suffix}",
        )
    )
    connection = connect_sqlite(write_database)
    try:
        row = connection.execute("SELECT version FROM runs WHERE id = 'run-1';").fetchone()
        return int(row[0])
    finally:
        connection.close()


def _prepare_effect_write_plan(
    *,
    write_database: Path,
    clock: FakeClock,
    suffix: str,
    tool_name: str,
    arguments: dict[str, object],
    expected: dict[str, object],
    target_resource_ref_id: str | None = None,
) -> None:
    save_service = SaveWritePlanService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )
    publish_service = PublishWritePlanService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )
    saved = save_service(
        SaveWritePlanCommand(
            command_id=f"save-{suffix}",
            request_hash="a0" * 32,
            plan_id=f"plan-{suffix}",
            run_id="run-1",
            revision_no=1,
            summary_text=f"prepare {tool_name} effect",
            expected_run_version=0,
            actions=(
                WriteActionDraft(
                    action_id=f"action-{suffix}",
                    position=1,
                    tool_name=tool_name,
                    arguments=arguments,
                    expected=expected,
                    evidence_ids=(f"evidence-{suffix}",),
                    target_resource_ref_id=target_resource_ref_id,
                ),
            ),
            evidence=(
                WriteEvidenceDraft(
                    evidence_id=f"evidence-{suffix}",
                    origin_type=EvidenceOriginType.DERIVED,
                    kind="USER_REQUEST",
                    excerpt=f"prepare {tool_name} effect",
                ),
            ),
        )
    )
    assert saved.applied is True
    published = publish_service(
        PublishWritePlanCommand(
            command_id=f"publish-{suffix}",
            request_hash="b0" * 32,
            plan_id=f"plan-{suffix}",
            run_id="run-1",
            expected_run_version=saved.run_version,
        )
    )
    assert published.applied is True


def _approve_effect_action(
    *, write_database: Path, clock: FakeClock, suffix: str
) -> WriteActionResponse:
    return ApproveWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )(
        ApproveWriteActionCommand(
            command_id=f"approve-{suffix}",
            request_hash="c0" * 32,
            action_id=f"action-{suffix}",
            expected_version=0,
            approved_by_account_id="account-1",
            approved_by_display="User",
            source_snapshot={},
            approval_id=f"approval-{suffix}",
            idempotency_key=(f"approve-{suffix}".encode().hex())[:64].ljust(64, "0"),
        )
    )


def _claim_effect_action(
    *,
    write_database: Path,
    clock: FakeClock,
    suffix: str,
    expected_version: int,
) -> WriteActionResponse:
    return ClaimWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
        signing_secret="phase-e-secret",
        service_instance_id="write-svc-1",
    )(
        ClaimWriteActionCommand(
            command_id=f"claim-{suffix}",
            request_hash="d0" * 32,
            action_id=f"action-{suffix}",
            expected_version=expected_version,
            source_snapshot={},
            attempt_id=f"attempt-{suffix}",
            nonce=f"nonce-{suffix}",
        )
    )


def _mark_effect_unknown(
    *,
    write_database: Path,
    clock: FakeClock,
    suffix: str,
    error: GoogleWorkspaceGatewayError,
) -> WriteActionResponse:
    return MarkWriteActionUnknownResultService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )(
        MarkWriteActionUnknownResultCommand(
            command_id=f"unknown-{suffix}",
            request_hash="e1" * 32,
            action_id=f"action-{suffix}",
            attempt_id=f"attempt-{suffix}",
            expected_action_version=2,
            expected_attempt_version=0,
            error_code=error.code.value,
            error_detail=str(error),
        )
    )


def _insert_calendar_event_reference(write_database: Path, *, version: str = "7") -> None:
    connection = connect_sqlite(write_database)
    try:
        connection.execute(
            """
            INSERT INTO resource_refs (
                id, run_id, source, resource_type, resource_id, parent_resource_id,
                canonical_url, title, event_time_ms, version_token, metadata_json, captured_at_ms
            ) VALUES (
                'resource-event-focus', 'run-1', 'CALENDAR', 'EVENT',
                'event-focus', 'calendar-primary', NULL, 'Focus block', NULL, ?, ?, 1000
            );
            """,
            (
                version,
                '{"end":"2026-11-01T09:00:00-07:00","event_kind":"focusTime",'
                '"start":"2026-11-01T08:00:00-07:00","status":"confirmed",'
                '"title":"Focus block","transparency":"busy"}',
            ),
        )
    finally:
        connection.close()


def _prepare_update_claimed_action(
    *,
    write_database: Path,
    clock: FakeClock,
    suffix: str,
) -> WriteActionResponse:
    source_payload = {
        "title": "Reply to project sync",
        "notes": "Reference the Thursday summary.",
        "due": "2026-08-07",
        "status": "needsAction",
    }
    source_snapshot = _expected_task_projection(
        resource_id="task-followup",
        payload=source_payload,
        version="4",
    )
    connection = connect_sqlite(write_database)
    try:
        connection.execute(
            """
            INSERT INTO resource_refs (
                id, run_id, source, resource_type, resource_id, parent_resource_id,
                canonical_url, title, event_time_ms, version_token, metadata_json, captured_at_ms
            )
            VALUES (
                ?, 'run-1', 'TASKS', 'TASK', 'task-followup', 'task-list-default',
                NULL, 'Reply to project sync', NULL, '4', ?, 1000
            );
            """,
            (
                "resource-ref-run-1-task-task-followup",
                (
                    '{"due":"2026-08-07","notes":"Reference the Thursday summary.",'
                    '"status":"needsAction","title":"Reply to project sync"}'
                ),
            ),
        )
    finally:
        connection.close()

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
    updated_payload = dict(source_payload)
    updated_payload["title"] = "Updated from retry preparation"
    save_service(
        SaveWritePlanCommand(
            command_id=f"save-{suffix}",
            request_hash="y1" * 32,
            plan_id=f"plan-{suffix}",
            run_id="run-1",
            revision_no=1,
            summary_text="prepare update plan",
            expected_run_version=0,
            actions=(
                WriteActionDraft(
                    action_id=f"action-{suffix}",
                    position=1,
                    tool_name="tasks_update_task",
                    arguments={
                        "task_list_id": "task-list-default",
                        "task_id": "task-followup",
                        "payload": {"title": "Updated from retry preparation"},
                    },
                    expected=_expected_task_projection(
                        resource_id="task-followup",
                        payload=updated_payload,
                        version="5",
                    ),
                    evidence_ids=(f"evidence-{suffix}",),
                    target_resource_ref_id="resource-ref-run-1-task-task-followup",
                ),
            ),
            evidence=(
                WriteEvidenceDraft(
                    evidence_id=f"evidence-{suffix}",
                    origin_type=EvidenceOriginType.DERIVED,
                    kind="USER_REQUEST",
                    excerpt="prepare update plan",
                ),
            ),
        )
    )
    publish_service(
        PublishWritePlanCommand(
            command_id=f"publish-{suffix}",
            request_hash="y2" * 32,
            plan_id=f"plan-{suffix}",
            run_id="run-1",
            expected_run_version=0,
        )
    )
    approve_service(
        ApproveWriteActionCommand(
            command_id=f"approve-{suffix}",
            request_hash="y3" * 32,
            action_id=f"action-{suffix}",
            expected_version=0,
            approved_by_account_id="account-1",
            approved_by_display="User",
            source_snapshot=source_snapshot,
            approval_id=f"approval-{suffix}",
            idempotency_key="y4" * 32,
        )
    )
    return claim_service(
        ClaimWriteActionCommand(
            command_id=f"claim-{suffix}",
            request_hash="y5" * 32,
            action_id=f"action-{suffix}",
            expected_version=1,
            source_snapshot=source_snapshot,
            attempt_id=f"attempt-{suffix}",
            nonce=f"nonce-{suffix}",
        )
    )


def _expected_task_projection(
    *,
    resource_id: str,
    payload: Mapping[str, object],
    version: str,
) -> dict[str, object]:
    return {
        "resource_type": "task",
        "resource_id": resource_id,
        "parent_id": "task-list-default",
        "version": version,
        "payload": dict(payload),
    }
