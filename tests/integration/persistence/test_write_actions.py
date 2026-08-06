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
    PublishWritePlanCommand,
    PublishWritePlanService,
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
from google_work_agent.domain import ResultCode
from google_work_agent.ports import EvidenceOriginType
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
                (SELECT COUNT(*) FROM verifications WHERE status = 'VERIFIED') AS verified_count;
            """
        ).fetchone()
        assert tuple(rows) == ("MISMATCH", "MISMATCH", 0)
    finally:
        connection.close()


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
