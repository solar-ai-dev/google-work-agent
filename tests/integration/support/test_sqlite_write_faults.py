import sqlite3
from pathlib import Path

import pytest

from google_work_agent.adapters.connectors.google_workspace import (
    GOOGLE_WORKSPACE_CONNECTOR_ID,
)
from google_work_agent.adapters.persistence import (
    apply_migrations,
    connect_sqlite,
    sqlite_unit_of_work_factory,
)
from google_work_agent.application.write_approval import ApproveWriteActionService
from google_work_agent.application.write_approval_contracts import (
    ApproveWriteActionCommand,
)
from google_work_agent.application.write_claim import ClaimWriteActionService
from google_work_agent.application.write_execution import ExecuteWriteActionService
from google_work_agent.application.write_execution_contracts import (
    ClaimWriteActionCommand,
    StoreWriteActionSuccessCommand,
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
from google_work_agent.application.write_result_persistence import (
    StoreWriteActionSuccessService,
)
from google_work_agent.ports import EvidenceOriginType
from tests.support.fakes import (
    FakeClockPort,
    FakeGoogleGateway,
    SQLiteFaultPlan,
    SQLiteFaultStage,
    fault_injecting_unit_of_work_factory,
)
from tests.support.fixtures import ProductFixtureSnapshotLoader

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "product"


@pytest.fixture()
def write_fault_database(tmp_path: Path) -> Path:
    database_path = tmp_path / "write-faults.db"
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
def fault_gateway() -> FakeGoogleGateway:
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    return FakeGoogleGateway(snapshot)


def test_store_write_success_fault_rolls_back_receipt_trace_resource_and_action_state(
    write_fault_database: Path,
    fault_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClockPort(1000)
    claim_token = _prepare_claimed_write_action(write_fault_database, clock)
    execute_service = ExecuteWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_fault_database),
        gateway=fault_gateway,
        now_ms=clock.now_ms,
        signing_secret="phase-e-secret",
        service_instance_id="write-svc-1",
    )
    executed = execute_service(
        action_id="action-fault",
        claim_token=claim_token,
    )
    store_service = StoreWriteActionSuccessService(
        unit_of_work_factory=fault_injecting_unit_of_work_factory(
            write_fault_database,
            SQLiteFaultPlan(stage=SQLiteFaultStage.AFTER_TRACE_INSERT),
        ),
        now_ms=clock.now_ms,
    )

    with pytest.raises(sqlite3.OperationalError):
        store_service(
            StoreWriteActionSuccessCommand(
                command_id="store-fault",
                request_hash="h1" * 32,
                action_id="action-fault",
                attempt_id="attempt-fault",
                expected_action_version=2,
                expected_attempt_version=0,
                snapshot=executed.snapshot,
            )
        )

    connection = connect_sqlite(write_fault_database)
    try:
        action_row = connection.execute(
            "SELECT status, version FROM actions WHERE id = 'action-fault';"
        ).fetchone()
        attempt_row = connection.execute(
            "SELECT status, version FROM execution_attempts WHERE id = 'attempt-fault';"
        ).fetchone()
        counts = connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM resource_refs) AS resource_count,
                (
                    SELECT COUNT(*)
                    FROM command_receipts
                    WHERE command_id = 'store-fault'
                ) AS receipt_count,
                (
                    SELECT COUNT(*)
                    FROM trace_events
                    WHERE action_id = 'action-fault'
                      AND event_type = 'WRITE_ACTION_EXECUTED'
                ) AS trace_count;
            """
        ).fetchone()
        assert action_row["status"] == "EXECUTING"
        assert action_row["version"] == 2
        assert attempt_row["status"] == "CLAIMED"
        assert attempt_row["version"] == 0
        assert tuple(counts) == (0, 0, 0)
    finally:
        connection.close()


def _prepare_claimed_write_action(database_path: Path, clock: FakeClockPort) -> str:
    payload: dict[str, object] = {
        "resource_id": "task-fault",
        "title": "fault",
        "status": "needsAction",
    }
    expected: dict[str, object] = {
        "resource_type": "task",
        "resource_id": "task-fault",
        "parent_id": "task-list-default",
        "version": "1",
        "payload": payload,
    }
    save_service = SaveWritePlanService(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        now_ms=clock.now_ms,
    )
    publish_service = PublishWritePlanService(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        now_ms=clock.now_ms,
    )
    approve_service = ApproveWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        now_ms=clock.now_ms,
    )
    claim_service = ClaimWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        now_ms=clock.now_ms,
        signing_secret="phase-e-secret",
        service_instance_id="write-svc-1",
    )
    save_service(
        SaveWritePlanCommand(
            command_id="save-fault",
            request_hash="i1" * 32,
            plan_id="plan-fault",
            run_id="run-1",
            revision_no=1,
            summary_text="fault",
            expected_run_version=0,
            actions=(
                WriteActionDraft(
                    action_id="action-fault",
                    connector_id=GOOGLE_WORKSPACE_CONNECTOR_ID,
                    position=1,
                    tool_name="tasks_create_task",
                    arguments={"task_list_id": "task-list-default", "payload": payload},
                    expected=expected,
                    evidence_ids=("evidence-fault",),
                ),
            ),
            evidence=(
                WriteEvidenceDraft(
                    evidence_id="evidence-fault",
                    origin_type=EvidenceOriginType.DERIVED,
                    kind="USER_REQUEST",
                    excerpt="fault",
                ),
            ),
        )
    )
    publish_service(
        PublishWritePlanCommand(
            command_id="publish-fault",
            request_hash="i2" * 32,
            plan_id="plan-fault",
            run_id="run-1",
            expected_run_version=0,
        )
    )
    approve_service(
        ApproveWriteActionCommand(
            command_id="approve-fault",
            request_hash="i3" * 32,
            action_id="action-fault",
            expected_version=0,
            approved_by_account_id="account-1",
            approved_by_display="User",
            source_snapshot={},
            approval_id="approval-fault",
            idempotency_key="i4" * 32,
        )
    )
    claimed = claim_service(
        ClaimWriteActionCommand(
            command_id="claim-fault",
            request_hash="i5" * 32,
            action_id="action-fault",
            expected_version=1,
            source_snapshot={},
            attempt_id="attempt-fault",
            nonce="nonce-fault",
        )
    )
    if claimed.claim_token is None:
        raise AssertionError("claim token was not issued")
    return claimed.claim_token
