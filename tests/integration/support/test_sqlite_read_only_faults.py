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
from google_work_agent.application.read_contracts import (
    ClaimReadActionCommand,
    CompleteReadActionCommand,
    FinalizeReadActionCommand,
    PublishReadOnlyPlanCommand,
    ReadActionDraft,
    ReadEvidenceDraft,
    SaveReadOnlyPlanCommand,
)
from google_work_agent.application.read_execution import ExecuteReadActionService
from google_work_agent.application.read_plan import (
    SaveReadOnlyPlanService,
)
from google_work_agent.application.use_cases.action.claim_read_action import ClaimReadActionHandler
from google_work_agent.application.use_cases.action.complete_read_action import (
    CompleteReadActionHandler,
)
from google_work_agent.application.use_cases.action.finalize_read_action import (
    FinalizeReadActionHandler,
)
from google_work_agent.application.use_cases.plan.publish_read_only_plan import (
    PublishReadOnlyPlanHandler,
)
from google_work_agent.domain.evidence.model import EvidenceOriginType
from tests.support.fakes import (
    FakeGoogleGateway,
    SQLiteFaultPlan,
    SQLiteFaultStage,
    fault_injecting_unit_of_work_factory,
)
from tests.support.fixtures import ProductFixtureSnapshotLoader

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "product"


@pytest.fixture()
def read_only_fault_database(tmp_path: Path) -> Path:
    database_path = tmp_path / "read-only-faults.db"
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


def test_complete_read_action_fault_rolls_back_resource_evidence_receipt_and_action_state(
    read_only_fault_database: Path,
    fault_gateway: FakeGoogleGateway,
) -> None:
    _prepare_single_action_plan(
        read_only_fault_database, plan_id="plan-fault", action_id="action-fault"
    )
    execute_service = ExecuteReadActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(read_only_fault_database),
        gateway=fault_gateway,
    )
    executed = execute_service(action_id="action-fault")
    complete_service = CompleteReadActionHandler(
        unit_of_work_factory=fault_injecting_unit_of_work_factory(
            read_only_fault_database,
            SQLiteFaultPlan(stage=SQLiteFaultStage.AFTER_TRACE_INSERT),
        ),
        now_ms=lambda: 1030,
    )

    with pytest.raises(sqlite3.OperationalError):
        complete_service(
            CompleteReadActionCommand(
                command_id="complete-fault",
                request_hash="a" * 64,
                action_id="action-fault",
                expected_version=1,
                output_json=executed.output_json,
                resource_refs=executed.resource_refs,
                evidence=executed.evidence,
            )
        )

    connection = connect_sqlite(read_only_fault_database)
    try:
        action_row = connection.execute(
            "SELECT status, version FROM actions WHERE id = 'action-fault';"
        ).fetchone()
        counts = connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM resource_refs) AS resource_count,
                (
                    SELECT COUNT(*)
                    FROM evidence
                    WHERE id <> 'evidence-plan'
                ) AS derived_evidence_count,
                (
                    SELECT COUNT(*)
                    FROM trace_events
                    WHERE action_id = 'action-fault'
                      AND event_type = 'READ_ACTION_COMPLETED'
                ) AS trace_count,
                (
                    SELECT COUNT(*)
                    FROM command_receipts
                    WHERE command_id = 'complete-fault'
                ) AS receipt_count;
            """
        ).fetchone()
        assert action_row["status"] == "EXECUTING"
        assert action_row["version"] == 1
        assert tuple(counts) == (0, 0, 0, 0)
    finally:
        connection.close()


def test_finalize_read_action_fault_rolls_back_parent_aggregate_reconciliation(
    read_only_fault_database: Path,
    fault_gateway: FakeGoogleGateway,
) -> None:
    _prepare_single_action_plan(
        read_only_fault_database, plan_id="plan-finalize", action_id="action-finalize"
    )
    execute_service = ExecuteReadActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(read_only_fault_database),
        gateway=fault_gateway,
    )
    executed = execute_service(action_id="action-finalize")
    CompleteReadActionHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(read_only_fault_database),
        now_ms=lambda: 1030,
    )(
        CompleteReadActionCommand(
            command_id="complete-ok",
            request_hash="b" * 64,
            action_id="action-finalize",
            expected_version=1,
            output_json=executed.output_json,
            resource_refs=executed.resource_refs,
            evidence=executed.evidence,
        )
    )
    finalize_service = FinalizeReadActionHandler(
        unit_of_work_factory=fault_injecting_unit_of_work_factory(
            read_only_fault_database,
            SQLiteFaultPlan(stage=SQLiteFaultStage.AFTER_AGGREGATE_UPDATE),
        ),
        now_ms=lambda: 1040,
    )

    with pytest.raises(sqlite3.OperationalError):
        finalize_service(
            FinalizeReadActionCommand(
                command_id="finalize-fault",
                request_hash="c" * 64,
                action_id="action-finalize",
                expected_version=2,
            )
        )

    connection = connect_sqlite(read_only_fault_database)
    try:
        action_row = connection.execute(
            "SELECT status, version FROM actions WHERE id = 'action-finalize';"
        ).fetchone()
        plan_row = connection.execute(
            "SELECT status FROM plans WHERE id = 'plan-finalize';"
        ).fetchone()
        run_row = connection.execute(
            "SELECT status, version, finished_at_ms FROM runs WHERE id = 'run-1';"
        ).fetchone()
        counts = connection.execute(
            """
            SELECT
                (
                    SELECT COUNT(*)
                    FROM trace_events
                    WHERE action_id = 'action-finalize'
                      AND event_type = 'READ_ACTION_FINALIZED'
                ) AS trace_count,
                (
                    SELECT COUNT(*)
                    FROM command_receipts
                    WHERE command_id = 'finalize-fault'
                ) AS receipt_count;
            """
        ).fetchone()
        assert action_row["status"] == "EXECUTED"
        assert action_row["version"] == 2
        assert plan_row["status"] == "ACTIVE"
        assert run_row["status"] == "EXECUTING"
        assert run_row["version"] == 1
        assert run_row["finished_at_ms"] is None
        assert tuple(counts) == (0, 0)
    finally:
        connection.close()


def _prepare_single_action_plan(database_path: Path, *, plan_id: str, action_id: str) -> None:
    save_service = SaveReadOnlyPlanService(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        now_ms=lambda: 1000,
    )
    publish_service = PublishReadOnlyPlanHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        now_ms=lambda: 1010,
    )
    claim_service = ClaimReadActionHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        now_ms=lambda: 1020,
    )

    save_service(
        SaveReadOnlyPlanCommand(
            command_id=f"save-{plan_id}",
            request_hash="d" * 64,
            plan_id=plan_id,
            run_id="run-1",
            revision_no=1,
            summary_text="Fault test",
            expected_run_version=0,
            actions=(
                ReadActionDraft(
                    action_id=action_id,
                    connector_id=GOOGLE_WORKSPACE_CONNECTOR_ID,
                    position=1,
                    tool_name="gmail_get_thread",
                    arguments={"thread_id": "thread-project"},
                    expected={"resource_type": "gmail_thread"},
                    evidence_ids=("evidence-plan",),
                ),
            ),
            evidence=(
                ReadEvidenceDraft(
                    evidence_id="evidence-plan",
                    origin_type=EvidenceOriginType.DERIVED,
                    kind="USER_REQUEST",
                    excerpt="Fault test evidence",
                ),
            ),
        )
    )
    publish_service(
        PublishReadOnlyPlanCommand(
            command_id=f"publish-{plan_id}",
            request_hash="e" * 64,
            plan_id=plan_id,
            run_id="run-1",
            expected_run_version=0,
        )
    )
    claim_service(
        ClaimReadActionCommand(
            command_id=f"claim-{plan_id}",
            request_hash="f" * 64,
            action_id=action_id,
            expected_version=0,
        )
    )
