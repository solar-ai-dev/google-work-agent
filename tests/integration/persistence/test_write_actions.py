import sqlite3
from collections.abc import Mapping
from json import loads
from pathlib import Path
from typing import cast

import pytest

from google_work_agent.adapters.connectors.google_workspace_execution import (
    GoogleWorkspaceExecutionBackend,
)
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
from google_work_agent.application.queries import QueryService
from google_work_agent.application.write_actions import (
    DeliveryCertainty,
    classify_write_delivery,
    is_reauth_required_error,
)
from google_work_agent.domain import (
    CalendarWorkHours,
    InvariantViolationError,
    PolicyViolationError,
    ResultCode,
    RunCommand,
    RunStatus,
)
from google_work_agent.ports import (
    EvidenceOriginType,
    FreeBusyCalendar,
    GoogleWorkspaceErrorCode,
    GoogleWorkspaceGateway,
    GoogleWorkspaceGatewayError,
    ResourcePage,
    ResourceSnapshot,
    ResourceType,
    TimeRange,
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


def test_task_delete_uses_preflight_claim_get_absent_and_verification(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClock(1000)
    _insert_task_delete_reference(write_database)
    _prepare_effect_write_plan(
        write_database=write_database,
        clock=clock,
        suffix="task-delete",
        tool_name="tasks_delete_task",
        arguments={"task_list_id": "task-list-default", "task_id": "task-followup"},
        expected={"resource_type": "task", "resource_id": "task-followup", "absent": True},
        target_resource_ref_id="resource-task-followup",
    )
    approved = _approve_effect_action(
        write_database=write_database,
        clock=clock,
        suffix="task-delete",
    )
    PreflightWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        gateway=fixture_gateway,
    )(action_id="action-task-delete")
    claimed = _claim_effect_action(
        write_database=write_database,
        clock=clock,
        suffix="task-delete",
        expected_version=approved.action_version,
    )
    executed = ExecuteWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        gateway=fixture_gateway,
        now_ms=clock.now_ms,
        signing_secret="phase-e-secret",
        service_instance_id="write-svc-1",
    )(action_id="action-task-delete", claim_token=claimed.claim_token or "")
    stored = StoreWriteActionSuccessService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )(
        StoreWriteActionSuccessCommand(
            command_id="store-task-delete",
            request_hash="d3" * 32,
            action_id="action-task-delete",
            attempt_id="attempt-task-delete",
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
            command_id="verify-task-delete",
            request_hash="d4" * 32,
            action_id="action-task-delete",
            attempt_id="attempt-task-delete",
            expected_action_version=stored.action_version,
            verification_id="verification-task-delete",
        )
    )

    assert verified.action_status == "VERIFIED"
    assert fixture_gateway.count_calls("delete_task") == 1
    assert fixture_gateway.count_calls("get_task") == 1


def test_task_delete_preflight_rejects_ambiguous_target_without_persisted_reference(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClock(1000)
    _prepare_effect_write_plan(
        write_database=write_database,
        clock=clock,
        suffix="task-delete-ambiguous",
        tool_name="tasks_delete_task",
        arguments={"task_list_id": "task-list-default", "task_id": "task-followup"},
        expected={"resource_type": "task", "resource_id": "task-followup", "absent": True},
        target_resource_ref_id=None,
        evidence_count=2,
    )
    _approve_effect_action(
        write_database=write_database, clock=clock, suffix="task-delete-ambiguous"
    )

    with pytest.raises(PolicyViolationError, match="persisted target reference"):
        PreflightWriteActionService(
            unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
            gateway=fixture_gateway,
        )(action_id="action-task-delete-ambiguous")

    assert fixture_gateway.count_calls("delete_task") == 0


def test_task_delete_preflight_rejects_target_version_change(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClock(1000)
    _insert_task_delete_reference(write_database, version="99")
    _prepare_effect_write_plan(
        write_database=write_database,
        clock=clock,
        suffix="task-delete-stale",
        tool_name="tasks_delete_task",
        arguments={"task_list_id": "task-list-default", "task_id": "task-followup"},
        expected={"resource_type": "task", "resource_id": "task-followup", "absent": True},
        target_resource_ref_id="resource-task-followup",
    )
    _approve_effect_action(write_database=write_database, clock=clock, suffix="task-delete-stale")

    with pytest.raises(PolicyViolationError, match="target version mismatch"):
        PreflightWriteActionService(
            unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
            gateway=fixture_gateway,
        )(action_id="action-task-delete-stale")

    assert fixture_gateway.count_calls("delete_task") == 0


def test_unknown_task_delete_recovers_from_target_absence_without_redelete(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClock(1000)
    _insert_task_delete_reference(write_database)
    _prepare_effect_write_plan(
        write_database=write_database,
        clock=clock,
        suffix="recover-task-delete",
        tool_name="tasks_delete_task",
        arguments={"task_list_id": "task-list-default", "task_id": "task-followup"},
        expected={"resource_type": "task", "resource_id": "task-followup", "absent": True},
        target_resource_ref_id="resource-task-followup",
    )
    approved = _approve_effect_action(
        write_database=write_database,
        clock=clock,
        suffix="recover-task-delete",
    )
    claimed = _claim_effect_action(
        write_database=write_database,
        clock=clock,
        suffix="recover-task-delete",
        expected_version=approved.action_version,
    )
    fixture_gateway.queue_fault(
        operation="delete_task",
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
            action_id="action-recover-task-delete",
            claim_token=claimed.claim_token or "",
        )
    _mark_effect_unknown(
        write_database=write_database,
        clock=clock,
        suffix="recover-task-delete",
        error=error_info.value,
    )

    recovered = RecoverUnknownDeleteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
        gateway=fixture_gateway,
    )(
        RecoverUnknownDeleteActionCommand(
            command_id="recover-task-delete-1",
            request_hash="f2" * 32,
            action_id="action-recover-task-delete",
            attempt_id="attempt-recover-task-delete",
            expected_action_version=3,
            expected_attempt_version=1,
        )
    )

    assert recovered.action_status == "EXECUTED"
    assert fixture_gateway.count_calls("delete_task") == 1


def test_unknown_task_delete_with_present_target_requires_reapproval_not_redelete(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClock(1000)
    _insert_task_delete_reference(write_database)
    _prepare_effect_write_plan(
        write_database=write_database,
        clock=clock,
        suffix="recover-task-delete-present",
        tool_name="tasks_delete_task",
        arguments={"task_list_id": "task-list-default", "task_id": "task-followup"},
        expected={"resource_type": "task", "resource_id": "task-followup", "absent": True},
        target_resource_ref_id="resource-task-followup",
    )
    approved = _approve_effect_action(
        write_database=write_database,
        clock=clock,
        suffix="recover-task-delete-present",
    )
    _claim_effect_action(
        write_database=write_database,
        clock=clock,
        suffix="recover-task-delete-present",
        expected_version=approved.action_version,
    )
    _mark_effect_unknown(
        write_database=write_database,
        clock=clock,
        suffix="recover-task-delete-present",
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
            command_id="recover-task-delete-present-1",
            request_hash="f3" * 32,
            action_id="action-recover-task-delete-present",
            attempt_id="attempt-recover-task-delete-present",
            expected_action_version=3,
            expected_attempt_version=1,
        )
    )

    assert recovered.result_code == ResultCode.RECOVERY_REQUIRED.value
    assert fixture_gateway.count_calls("delete_task") == 0


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
    assert _cancel_marker_count(write_database) == 1
    assert _action_cancelled_audit_count(write_database) == 1
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
    clock = FakeClock(1000)
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


def _seed_write_terminal_status(
    *, database_path: Path, action_id: str, terminal_status: str
) -> None:
    connection = connect_sqlite(database_path)
    try:
        approval_id = f"approval-{action_id}"
        attempt_id = f"attempt-{action_id}"
        connection.execute(
            "UPDATE actions SET status = 'APPROVED', version = 1 WHERE id = ?;", (action_id,)
        )
        connection.execute(
            """
            INSERT INTO approvals (
                id, action_id, approval_no, action_version, status, approved_by_account_id,
                arguments_snapshot_json, canonical_arguments_hash, source_snapshot_json,
                source_snapshot_hash, policy_version, tool_schema_version, idempotency_key,
                recovery_fingerprint, approved_at_ms, expires_at_ms
            ) VALUES (?, ?, 1, 1, 'ACTIVE', 'account-1', '{}', ?, '{}', ?, 'p1', 'v1', ?, ?, 1, 2);
            """,
            (
                approval_id,
                action_id,
                "a" * 64,
                "b" * 64,
                approval_id.ljust(64, "x")[:64],
                "c" * 64,
            ),
        )
        connection.execute(
            "UPDATE approvals SET status = 'CONSUMED', consumed_at_ms = 1 WHERE id = ?;",
            (approval_id,),
        )
        connection.execute(
            "UPDATE actions SET status = 'EXECUTING', version = 2 WHERE id = ?;", (action_id,)
        )
        connection.execute(
            """
            INSERT INTO execution_attempts (id, approval_id, attempt_no, status, started_at_ms)
            VALUES (?, ?, 1, 'CLAIMED', 1);
            """,
            (attempt_id, approval_id),
        )
        attempt_status = "FAILED" if terminal_status == "FAILED" else "SUCCEEDED"
        connection.execute(
            "UPDATE execution_attempts SET status = ? WHERE id = ?;",
            (attempt_status, attempt_id),
        )
        if terminal_status == "FAILED":
            connection.execute(
                "UPDATE actions SET status = 'FAILED', version = 3 WHERE id = ?;", (action_id,)
            )
        else:
            connection.execute(
                "UPDATE actions SET status = 'EXECUTED', version = 3 WHERE id = ?;", (action_id,)
            )
            connection.execute(
                """
                INSERT INTO verifications (
                    id, execution_attempt_id, verification_no, status, normalizer_version,
                    expected_json, actual_json, diff_json, verified_at_ms
                ) VALUES (?, ?, 1, 'MISMATCH', 'v1', '{}', '{}', '[]', 2);
                """,
                (f"verification-{action_id}", attempt_id),
            )
            connection.execute(
                "UPDATE actions SET status = 'MISMATCH', version = 4 WHERE id = ?;", (action_id,)
            )
        connection.commit()
    finally:
        connection.close()


def test_unknown_recovery_preserves_one_cancel_marker_and_finalizes_through_domain_commands(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClock(1000)
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
    clock = FakeClock(1000)
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
    clock = FakeClock(1000)
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
    clock = FakeClock(1000)
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


def _insert_action_sibling(
    *,
    database_path: Path,
    source_action_id: str,
    sibling_action_id: str,
    status: str,
) -> None:
    connection = connect_sqlite(database_path)
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
                ?, plan_id, 2, tool_name, effect_type, approval_requirement,
                verification_policy, recovery_policy, target_resource_ref_id, ?,
                arguments_json, arguments_hash, expected_json, risk_json, 0,
                created_at_ms, updated_at_ms
            FROM actions WHERE id = ?;
            """,
            (sibling_action_id, status, source_action_id),
        )
        connection.commit()
    finally:
        connection.close()


def _cancel_marker_count(database_path: Path) -> int:
    connection = connect_sqlite(database_path)
    try:
        row = connection.execute(
            """
            SELECT COUNT(*)
            FROM audit_events
            WHERE run_id = 'run-1'
              AND event_type = 'RUN_CANCELLATION_REQUESTED'
              AND outcome = 'TRANSITION_APPLIED';
            """
        ).fetchone()
        return int(row[0])
    finally:
        connection.close()


def _action_cancelled_audit_count(database_path: Path) -> int:
    connection = connect_sqlite(database_path)
    try:
        row = connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE event_type = 'ACTION_CANCELLED';"
        ).fetchone()
        return int(row[0])
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


def test_action_risk_defaults_to_empty_object_on_insert(write_database: Path) -> None:
    _prepare_write_plan(
        write_database=write_database,
        clock=FakeClock(1000),
        suffix="risk-default",
    )

    with sqlite_unit_of_work_factory(write_database)() as unit_of_work:
        action = unit_of_work.actions.get_by_id("action-risk-default")
        listed = unit_of_work.actions.list_by_plan("plan-risk-default")

    assert action is not None
    assert action.risk == {}
    assert listed[0].risk == {}
    connection = connect_sqlite(write_database)
    try:
        row = connection.execute(
            "SELECT risk_json FROM actions WHERE id = 'action-risk-default';"
        ).fetchone()
        assert str(row["risk_json"]) == "{}"
    finally:
        connection.close()


def test_action_risk_round_trips_through_repository_and_run_snapshot(
    write_database: Path,
) -> None:
    risk = {"z": ["경고", {"matched": True}], "a": 1}
    _prepare_write_plan(
        write_database=write_database,
        clock=FakeClock(1000),
        suffix="risk-roundtrip",
        risk=risk,
    )

    with sqlite_unit_of_work_factory(write_database)() as unit_of_work:
        action = unit_of_work.actions.get_by_id("action-risk-roundtrip")
        listed = unit_of_work.actions.list_by_plan("plan-risk-roundtrip")
        ready = unit_of_work.actions.list_ready_actions("plan-risk-roundtrip")

    assert action is not None
    assert action.risk == risk
    assert listed[0].risk == risk
    assert ready[0].risk == risk
    snapshot = QueryService(
        database_path=write_database,
        connection_factory=connect_sqlite,
        runtime_status_provider=None,  # type: ignore[arg-type]
    ).get_run_snapshot("run-1")
    assert snapshot is not None
    assert snapshot.actions[0].risk == risk

    connection = connect_sqlite(write_database)
    try:
        row = connection.execute(
            "SELECT risk_json FROM actions WHERE id = 'action-risk-roundtrip';"
        ).fetchone()
        assert str(row["risk_json"]) == '{"a":1,"z":["경고",{"matched":true}]}'
    finally:
        connection.close()


def test_action_risk_over_16_kib_is_rejected_before_plan_persistence(
    write_database: Path,
) -> None:
    service = SaveWritePlanService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=FakeClock(1000).now_ms,
    )
    with pytest.raises(InvariantViolationError, match="16 KiB"):
        service(
            SaveWritePlanCommand(
                command_id="save-risk-large",
                request_hash="91" * 32,
                plan_id="plan-risk-large",
                run_id="run-1",
                revision_no=1,
                summary_text="oversized risk",
                expected_run_version=0,
                actions=(
                    WriteActionDraft(
                        action_id="action-risk-large",
                        position=1,
                        tool_name="tasks_create_task",
                        arguments={
                            "task_list_id": "task-list-default",
                            "payload": {"title": "Risk limit"},
                        },
                        expected={},
                        evidence_ids=("evidence-risk-large",),
                        risk={"detail": "x" * (16 * 1024)},
                    ),
                ),
                evidence=(
                    WriteEvidenceDraft(
                        evidence_id="evidence-risk-large",
                        origin_type=EvidenceOriginType.DERIVED,
                        kind="USER_REQUEST",
                        excerpt="Create a task.",
                    ),
                ),
            )
        )

    connection = connect_sqlite(write_database)
    try:
        assert connection.execute("SELECT COUNT(*) FROM plans;").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM actions;").fetchone()[0] == 0
    finally:
        connection.close()


def test_repository_rejects_corrupt_persisted_action_risk(write_database: Path) -> None:
    _prepare_write_plan(
        write_database=write_database,
        clock=FakeClock(1000),
        suffix="risk-corrupt",
    )
    connection = connect_sqlite(write_database)
    try:
        connection.execute("PRAGMA ignore_check_constraints = ON;")
        connection.execute(
            "UPDATE actions SET risk_json = 'not-json' WHERE id = 'action-risk-corrupt';"
        )
        connection.commit()
    finally:
        connection.close()

    with (
        sqlite_unit_of_work_factory(write_database)() as unit_of_work,
        pytest.raises(InvariantViolationError, match="not valid JSON"),
    ):
        unit_of_work.actions.get_by_id("action-risk-corrupt")


def _duplicate_risk(
    decision: str,
    *,
    matched_ids: tuple[str, ...] = (),
    freshness: str = "EVIDENCE_ONLY",
) -> dict[str, object]:
    return {
        "duplicate": {
            "decision": decision,
            "matched_resource_ids": list(matched_ids),
            "reason_codes": [
                "NO_MATCHING_INCOMPLETE_TASK"
                if decision == "NOT_DUPLICATE"
                else "TITLE_EXACT_DATE_EXACT"
                if decision == "CLEAR_DUPLICATE"
                else "TITLE_EXACT_DATE_DIFFERENT"
            ],
            "checked_at_ms": 1000,
            "freshness": freshness,
        }
    }


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
    clock = FakeClock(1000)
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
    clock = FakeClock(1000)
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


class _TaskDuplicatePreflightGateway:
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
        _assert_can_open_sqlite_write_transaction(self.database_path)
        self.calls += 1
        if self.error is not None:
            raise self.error
        return ResourcePage(items=self.tasks, next_page_token=None)


def _duplicate_task(resource_id: str, *, title: str) -> ResourceSnapshot:
    return ResourceSnapshot(
        fixture_snapshot_id=resource_id,
        resource_type=ResourceType.TASK,
        resource_id=resource_id,
        parent_id="task-list-default",
        related_resource_ids=("task-list-default",),
        version="1",
        recovery_fingerprint=None,
        payload={"title": title, "status": "needsAction"},
    )


def _approve_preflight_action(
    *, write_database: Path, clock: FakeClock, suffix: str, risk: dict[str, object]
) -> None:
    _prepare_write_plan(
        write_database=write_database,
        clock=clock,
        suffix=suffix,
        risk=risk,
    )
    response = ApproveWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )(
        ApproveWriteActionCommand(
            command_id=f"approve-{suffix}",
            request_hash="fe" * 32,
            action_id=f"action-{suffix}",
            expected_version=0,
            approved_by_account_id="account-1",
            approved_by_display="User",
            source_snapshot={},
            approval_id=f"approval-{suffix}",
            idempotency_key="ff" * 32,
            duplicate_acknowledged=True,
        )
    )
    assert response.applied is True


def test_task_duplicate_preflight_new_match_revokes_stale_approval(
    write_database: Path,
) -> None:
    clock = FakeClock(1000)
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
    clock = FakeClock(1000)
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
    clock = FakeClock(1000)
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


class _FeasibilityPreflightGateway:
    def __init__(
        self, *, busy_event: ResourceSnapshot | None = None, error: Exception | None = None
    ) -> None:
        self.busy_event = busy_event
        self.error = error

    def list_calendar_events(self, **kwargs: object) -> ResourcePage:
        if self.error is not None and str(kwargs.get("time_max", "")).endswith("18:00:00+09:00"):
            raise self.error
        is_horizon = str(kwargs.get("time_max", "")).endswith("18:00:00+09:00")
        items = (self.busy_event,) if is_horizon and self.busy_event is not None else ()
        return ResourcePage(items=items, next_page_token=None)

    def query_freebusy(
        self, *, calendar_ids: tuple[str, ...], time_range: TimeRange
    ) -> tuple[FreeBusyCalendar, ...]:
        del time_range
        return (FreeBusyCalendar(calendar_id=calendar_ids[0], intervals=()),)


def _feasibility_risk(decision: str, *, best_minutes: int) -> dict[str, object]:
    return {
        "calendar_conflict": {
            "decision": "NO_CONFLICT",
            "matched_resource_ids": [],
            "reason_codes": ["NO_CONFLICT"],
            "checked_at_ms": 1000,
            "freshness": "EVIDENCE_ONLY",
        },
        "feasibility_input": {
            "business_deadline": "1970-01-01",
            "business_deadline_source": "USER",
            "required_duration_minutes": 120,
            "duration_source": "EXPLICIT_ESTIMATE",
        },
        "feasibility": {
            "decision": decision,
            "reason_codes": [
                "CLEAN_SLOT_AVAILABLE" if decision == "FEASIBLE" else "NO_CONTIGUOUS_SLOT"
            ],
            "business_deadline": "1970-01-01",
            "derived_cutoff": "1970-01-01T18:00:00+09:00",
            "required_duration_minutes": 120,
            "best_clean_slot_minutes": best_minutes,
            "best_warning_slot_minutes": best_minutes,
            "checked_at_ms": 1000,
            "freshness": "EVIDENCE_ONLY",
        },
    }


def _prepare_calendar_feasibility_action(
    *, write_database: Path, clock: FakeClock, suffix: str, risk: dict[str, object]
) -> WriteActionResponse:
    payload = {
        "summary": "work block",
        "start": "1970-01-01T09:00:00+09:00",
        "end": "1970-01-01T10:00:00+09:00",
    }
    save = SaveWritePlanService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database), now_ms=clock.now_ms
    )
    publish = PublishWritePlanService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database), now_ms=clock.now_ms
    )
    save(
        SaveWritePlanCommand(
            command_id=f"save-{suffix}",
            request_hash="a1" * 32,
            plan_id=f"plan-{suffix}",
            run_id="run-1",
            revision_no=1,
            summary_text="calendar feasibility",
            expected_run_version=0,
            actions=(
                WriteActionDraft(
                    action_id=f"action-{suffix}",
                    position=1,
                    tool_name="calendar_create_event",
                    arguments={"calendar_id": "primary", "payload": payload},
                    expected={
                        "resource_type": "calendar_event",
                        "resource_id": None,
                        "payload": payload,
                    },
                    evidence_ids=(f"evidence-{suffix}",),
                    risk=risk,
                ),
            ),
            evidence=(
                WriteEvidenceDraft(
                    evidence_id=f"evidence-{suffix}",
                    origin_type=EvidenceOriginType.DERIVED,
                    kind="USER_REQUEST",
                    excerpt="calendar feasibility",
                ),
            ),
        )
    )
    publish(
        PublishWritePlanCommand(
            command_id=f"publish-{suffix}",
            request_hash="a2" * 32,
            plan_id=f"plan-{suffix}",
            run_id="run-1",
            expected_run_version=0,
        )
    )
    approved = ApproveWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database), now_ms=clock.now_ms
    )(
        ApproveWriteActionCommand(
            command_id=f"approve-{suffix}",
            request_hash="a3" * 32,
            action_id=f"action-{suffix}",
            expected_version=0,
            approved_by_account_id="account-1",
            approved_by_display="User",
            source_snapshot={},
            approval_id=f"approval-{suffix}",
            idempotency_key="a4" * 32,
        )
    )
    return approved


def test_infeasible_action_cannot_be_approved(write_database: Path) -> None:
    clock = FakeClock(1000)
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
    clock = FakeClock(1000)
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
    clock = FakeClock(1000)
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


def _prepare_write_plan(
    *,
    write_database: Path,
    clock: FakeClock,
    suffix: str,
    run_id: str = "run-1",
    risk: dict[str, object] | None = None,
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
                    risk={} if risk is None else risk,
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
    evidence_count: int = 1,
) -> None:
    save_service = SaveWritePlanService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )
    publish_service = PublishWritePlanService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )
    evidence_ids = tuple(f"evidence-{suffix}-{index}" for index in range(evidence_count))
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
                    evidence_ids=evidence_ids,
                    target_resource_ref_id=target_resource_ref_id,
                ),
            ),
            evidence=tuple(
                WriteEvidenceDraft(
                    evidence_id=evidence_id,
                    origin_type=EvidenceOriginType.DERIVED,
                    kind="USER_REQUEST",
                    excerpt=f"prepare {tool_name} effect",
                )
                for evidence_id in evidence_ids
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


def _insert_task_delete_reference(write_database: Path, *, version: str = "4") -> None:
    connection = connect_sqlite(write_database)
    try:
        connection.execute(
            """
            INSERT INTO resource_refs (
                id, run_id, source, resource_type, resource_id, parent_resource_id,
                canonical_url, title, event_time_ms, version_token, metadata_json, captured_at_ms
            ) VALUES (
                'resource-task-followup', 'run-1', 'TASKS', 'TASK',
                'task-followup', 'task-list-default', NULL, 'Reply to project sync',
                NULL, ?, ?, 1000
            );
            """,
            (
                version,
                '{"due":"2026-08-07","notes":"Reference the Thursday summary.",'
                '"status":"needsAction","title":"Reply to project sync"}',
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
