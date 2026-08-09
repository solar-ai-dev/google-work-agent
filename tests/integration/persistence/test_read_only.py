from pathlib import Path

import pytest

from google_work_agent.adapters.persistence import (
    apply_migrations,
    connect_sqlite,
    sqlite_unit_of_work_factory,
)
from google_work_agent.application import (
    ClaimReadActionCommand,
    ClaimReadActionService,
    CompletedEvidence,
    CompletedResourceRef,
    CompleteReadActionCommand,
    CompleteReadActionService,
    ExecuteReadActionService,
    FailReadActionCommand,
    FailReadActionService,
    FinalizeReadActionCommand,
    FinalizeReadActionService,
    PublishReadOnlyPlanCommand,
    PublishReadOnlyPlanService,
    ReadActionDraft,
    ReadEvidenceDraft,
    SaveReadOnlyPlanCommand,
    SaveReadOnlyPlanService,
)
from google_work_agent.domain import ResultCode, RunStatus
from google_work_agent.ports import (
    EvidenceOriginType,
    PlanStatus,
    ResourceSource,
    StoredResourceType,
)
from tests.support.fakes import FakeGoogleGateway
from tests.support.fixtures import ProductFixtureSnapshotLoader

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "product"


@pytest.fixture()
def read_only_database(tmp_path: Path) -> Path:
    database_path = tmp_path / "read-only.db"
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


def test_read_only_happy_path_persists_projection_and_completes_run(
    read_only_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    save_service = SaveReadOnlyPlanService(
        unit_of_work_factory=sqlite_unit_of_work_factory(read_only_database),
        now_ms=lambda: 1000,
    )
    publish_service = PublishReadOnlyPlanService(
        unit_of_work_factory=sqlite_unit_of_work_factory(read_only_database),
        now_ms=lambda: 1010,
    )
    claim_service = ClaimReadActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(read_only_database),
        now_ms=lambda: 1020,
    )
    execute_service = ExecuteReadActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(read_only_database),
        gateway=fixture_gateway,
    )
    complete_service = CompleteReadActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(read_only_database),
        now_ms=lambda: 1030,
    )
    finalize_service = FinalizeReadActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(read_only_database),
        now_ms=lambda: 1040,
    )

    saved = save_service(
        SaveReadOnlyPlanCommand(
            command_id="save-1",
            request_hash="a" * 64,
            plan_id="plan-1",
            run_id="run-1",
            revision_no=1,
            summary_text="Read one thread",
            expected_run_version=0,
            actions=(
                ReadActionDraft(
                    action_id="action-1",
                    position=1,
                    tool_name="gmail_get_thread",
                    arguments={"thread_id": "thread-project"},
                    expected={"resource_type": "gmail_thread"},
                    evidence_ids=("evidence-plan-1",),
                ),
            ),
            evidence=(
                ReadEvidenceDraft(
                    evidence_id="evidence-plan-1",
                    origin_type=EvidenceOriginType.DERIVED,
                    kind="USER_REQUEST",
                    excerpt="Summarize the project thread.",
                ),
            ),
        )
    )
    assert saved.applied is True
    assert saved.plan_status == PlanStatus.DRAFT.value

    published = publish_service(
        PublishReadOnlyPlanCommand(
            command_id="publish-1",
            request_hash="b" * 64,
            plan_id="plan-1",
            run_id="run-1",
            expected_run_version=0,
        )
    )
    assert published.applied is True
    assert published.plan_status == PlanStatus.ACTIVE.value
    assert published.run_status == RunStatus.EXECUTING.value
    assert published.run_version == 1

    claimed = claim_service(
        ClaimReadActionCommand(
            command_id="claim-1",
            request_hash="c" * 64,
            action_id="action-1",
            expected_version=0,
        )
    )
    assert claimed.applied is True
    assert claimed.action_status == "EXECUTING"

    connection = connect_sqlite(read_only_database)
    try:
        action_row = connection.execute(
            "SELECT status, version FROM actions WHERE id = 'action-1';"
        ).fetchone()
        assert action_row["status"] == "EXECUTING"
        assert action_row["version"] == 1
    finally:
        connection.close()

    executed = execute_service(action_id="action-1")
    assert fixture_gateway.call_log[-1].operation == "get_gmail_thread"

    completed = complete_service(
        CompleteReadActionCommand(
            command_id="complete-1",
            request_hash="d" * 64,
            action_id="action-1",
            expected_version=1,
            output_json=executed.output_json,
            resource_refs=executed.resource_refs,
            evidence=executed.evidence,
        )
    )
    assert completed.applied is True
    assert completed.action_status == "EXECUTED"

    finalized = finalize_service(
        FinalizeReadActionCommand(
            command_id="finalize-1",
            request_hash="e" * 64,
            action_id="action-1",
            expected_version=2,
        )
    )
    assert finalized.applied is True
    assert finalized.action_status == "VERIFIED"
    assert finalized.plan_completed is True
    assert finalized.run_completed is True
    assert finalized.partial is False

    connection = connect_sqlite(read_only_database)
    try:
        run_row = connection.execute(
            "SELECT status, version, finished_at_ms FROM runs WHERE id = 'run-1';"
        ).fetchone()
        plan_row = connection.execute("SELECT status FROM plans WHERE id = 'plan-1';").fetchone()
        resource_rows = connection.execute(
            """
            SELECT source, resource_type, resource_id, metadata_json
            FROM resource_refs
            WHERE run_id = 'run-1';
            """
        ).fetchall()
        evidence_rows = connection.execute(
            """
            SELECT origin_type, kind, excerpt
            FROM evidence
            WHERE run_id = 'run-1'
            ORDER BY id;
            """
        ).fetchall()
        receipt_rows = connection.execute(
            """
            SELECT command_id, status, result_code
            FROM command_receipts
            ORDER BY command_id;
            """
        ).fetchall()
        aggregate_counts = connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM approvals) AS approval_count,
                (SELECT COUNT(*) FROM execution_attempts) AS attempt_count,
                (SELECT COUNT(*) FROM verifications) AS verification_count;
            """
        ).fetchone()

        assert run_row["status"] == "COMPLETED"
        assert run_row["version"] == 2
        assert run_row["finished_at_ms"] == 1040
        assert plan_row["status"] == "COMPLETED"
        assert len(resource_rows) == 1
        assert resource_rows[0]["source"] == "GMAIL"
        assert resource_rows[0]["resource_type"] == "THREAD"
        assert resource_rows[0]["resource_id"] == "thread-project"
        assert '"participant_count": 2' in resource_rows[0]["metadata_json"]
        assert len(evidence_rows) == 2
        assert evidence_rows[0]["origin_type"] == "DERIVED"
        assert evidence_rows[1]["origin_type"] == "GOOGLE_RESOURCE"
        assert all(row["status"] == "APPLIED" for row in receipt_rows)
        assert tuple(aggregate_counts) == (0, 0, 0)
    finally:
        connection.close()


def test_read_only_failure_marks_dependency_blocked_and_keeps_independent_branch_running(
    read_only_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    save_service = SaveReadOnlyPlanService(
        unit_of_work_factory=sqlite_unit_of_work_factory(read_only_database),
        now_ms=lambda: 1000,
    )
    publish_service = PublishReadOnlyPlanService(
        unit_of_work_factory=sqlite_unit_of_work_factory(read_only_database),
        now_ms=lambda: 1010,
    )
    claim_service = ClaimReadActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(read_only_database),
        now_ms=lambda: 1020,
    )
    fail_service = FailReadActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(read_only_database),
        now_ms=lambda: 1030,
    )
    execute_service = ExecuteReadActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(read_only_database),
        gateway=fixture_gateway,
    )
    complete_service = CompleteReadActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(read_only_database),
        now_ms=lambda: 1040,
    )
    finalize_service = FinalizeReadActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(read_only_database),
        now_ms=lambda: 1050,
    )

    save_service(
        SaveReadOnlyPlanCommand(
            command_id="save-2",
            request_hash="f" * 64,
            plan_id="plan-2",
            run_id="run-1",
            revision_no=1,
            summary_text="Two branches",
            expected_run_version=0,
            actions=(
                ReadActionDraft(
                    action_id="action-root",
                    position=1,
                    tool_name="gmail_get_thread",
                    arguments={"thread_id": "thread-project"},
                    expected={"resource_type": "gmail_thread"},
                    evidence_ids=("evidence-plan-2",),
                ),
                ReadActionDraft(
                    action_id="action-dependent",
                    position=2,
                    tool_name="gmail_get_message",
                    arguments={"message_id": "message-project-1"},
                    expected={"resource_type": "gmail_message"},
                    evidence_ids=("evidence-plan-2",),
                    depends_on_action_ids=("action-root",),
                ),
                ReadActionDraft(
                    action_id="action-branch",
                    position=3,
                    tool_name="calendar_query_freebusy",
                    arguments={
                        "calendar_ids": ["calendar-primary"],
                        "time_min": "2026-11-01T00:00:00-07:00",
                        "time_max": "2026-11-02T00:00:00-08:00",
                    },
                    expected={"result_kind": "FREEBUSY"},
                    evidence_ids=("evidence-plan-2",),
                ),
            ),
            evidence=(
                ReadEvidenceDraft(
                    evidence_id="evidence-plan-2",
                    origin_type=EvidenceOriginType.DERIVED,
                    kind="USER_REQUEST",
                    excerpt="Check thread and freebusy.",
                ),
            ),
        )
    )
    publish_service(
        PublishReadOnlyPlanCommand(
            command_id="publish-2",
            request_hash="0" * 64,
            plan_id="plan-2",
            run_id="run-1",
            expected_run_version=0,
        )
    )

    blocked_claim = claim_service(
        ClaimReadActionCommand(
            command_id="claim-blocked",
            request_hash="1" * 64,
            action_id="action-dependent",
            expected_version=0,
        )
    )
    assert blocked_claim.applied is False
    assert blocked_claim.result_code == ResultCode.STATE_CONFLICT.value
    assert fixture_gateway.call_log == []

    claim_service(
        ClaimReadActionCommand(
            command_id="claim-root",
            request_hash="2" * 64,
            action_id="action-root",
            expected_version=0,
        )
    )
    failed = fail_service(
        FailReadActionCommand(
            command_id="fail-root",
            request_hash="3" * 64,
            action_id="action-root",
            expected_version=1,
            safe_error_code="UPSTREAM_5XX",
            retryable=True,
            safe_error_detail="gateway timeout",
        )
    )
    assert failed.applied is True
    assert failed.action_status == "FAILED"
    assert failed.plan_completed is False
    assert failed.run_completed is False
    assert failed.partial is True

    claimed_branch = claim_service(
        ClaimReadActionCommand(
            command_id="claim-branch",
            request_hash="4" * 64,
            action_id="action-branch",
            expected_version=0,
        )
    )
    assert claimed_branch.applied is True

    executed = execute_service(action_id="action-branch")
    completed = complete_service(
        CompleteReadActionCommand(
            command_id="complete-branch",
            request_hash="5" * 64,
            action_id="action-branch",
            expected_version=1,
            output_json=executed.output_json,
            resource_refs=executed.resource_refs,
            evidence=executed.evidence,
        )
    )
    assert completed.applied is True

    finalized = finalize_service(
        FinalizeReadActionCommand(
            command_id="finalize-branch",
            request_hash="6" * 64,
            action_id="action-branch",
            expected_version=2,
        )
    )
    assert finalized.applied is True
    assert finalized.plan_completed is True
    assert finalized.run_completed is True
    assert finalized.partial is True

    connection = connect_sqlite(read_only_database)
    try:
        status_rows = connection.execute(
            "SELECT id, status, version FROM actions ORDER BY position;"
        ).fetchall()
        run_row = connection.execute(
            "SELECT status, version, finished_at_ms FROM runs WHERE id = 'run-1';"
        ).fetchone()
        plan_row = connection.execute("SELECT status FROM plans WHERE id = 'plan-2';").fetchone()

        assert [(row["id"], row["status"]) for row in status_rows] == [
            ("action-root", "FAILED"),
            ("action-dependent", "DEPENDENCY_BLOCKED"),
            ("action-branch", "VERIFIED"),
        ]
        assert run_row["status"] == "COMPLETED"
        assert run_row["version"] == 2
        assert run_row["finished_at_ms"] == 1050
        assert plan_row["status"] == "COMPLETED"
    finally:
        connection.close()


def test_save_read_only_plan_rejects_non_read_tool_without_persisting_partial_rows(
    read_only_database: Path,
) -> None:
    service = SaveReadOnlyPlanService(
        unit_of_work_factory=sqlite_unit_of_work_factory(read_only_database),
        now_ms=lambda: 1000,
    )

    with pytest.raises(ValueError):
        service(
            SaveReadOnlyPlanCommand(
                command_id="save-invalid",
                request_hash="7" * 64,
                plan_id="plan-invalid",
                run_id="run-1",
                revision_no=1,
                summary_text="Invalid",
                expected_run_version=0,
                actions=(
                    ReadActionDraft(
                        action_id="action-invalid",
                        position=1,
                        tool_name="gmail_create_draft",
                        arguments={"payload": {"subject": "Nope"}},
                        expected={"resource_type": "gmail_draft"},
                        evidence_ids=("evidence-invalid",),
                    ),
                ),
                evidence=(
                    ReadEvidenceDraft(
                        evidence_id="evidence-invalid",
                        origin_type=EvidenceOriginType.DERIVED,
                        kind="USER_REQUEST",
                        excerpt="Should fail.",
                    ),
                ),
            )
        )

    connection = connect_sqlite(read_only_database)
    try:
        counts = connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM plans) AS plan_count,
                (SELECT COUNT(*) FROM actions) AS action_count,
                (SELECT COUNT(*) FROM evidence) AS evidence_count,
                (SELECT COUNT(*) FROM command_receipts) AS receipt_count;
            """
        ).fetchone()
        assert tuple(counts) == (0, 0, 0, 0)
    finally:
        connection.close()


def test_save_read_only_plan_replays_same_command_id_and_hash(
    read_only_database: Path,
) -> None:
    service = SaveReadOnlyPlanService(
        unit_of_work_factory=sqlite_unit_of_work_factory(read_only_database),
        now_ms=lambda: 1000,
    )
    command = SaveReadOnlyPlanCommand(
        command_id="save-replay",
        request_hash="8" * 64,
        plan_id="plan-replay",
        run_id="run-1",
        revision_no=1,
        summary_text="Replay",
        expected_run_version=0,
        actions=(
            ReadActionDraft(
                action_id="action-replay",
                position=1,
                tool_name="tasks_get_task",
                arguments={"task_list_id": "task-list-default", "task_id": "task-followup"},
                expected={"resource_type": "task"},
                evidence_ids=("evidence-replay",),
            ),
        ),
        evidence=(
            ReadEvidenceDraft(
                evidence_id="evidence-replay",
                origin_type=EvidenceOriginType.DERIVED,
                kind="USER_REQUEST",
                excerpt="Replay test",
            ),
        ),
    )

    first = service(command)
    second = service(command)

    assert second == first

    connection = connect_sqlite(read_only_database)
    try:
        counts = connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM plans) AS plan_count,
                (SELECT COUNT(*) FROM actions) AS action_count,
                (
                    SELECT COUNT(*)
                    FROM command_receipts
                    WHERE command_id = 'save-replay'
                ) AS receipt_count;
            """
        ).fetchone()
        assert tuple(counts) == (1, 1, 1)
    finally:
        connection.close()


def test_claim_read_action_rejects_stale_version_without_gateway_call(
    read_only_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    save_service = SaveReadOnlyPlanService(
        unit_of_work_factory=sqlite_unit_of_work_factory(read_only_database),
        now_ms=lambda: 1000,
    )
    publish_service = PublishReadOnlyPlanService(
        unit_of_work_factory=sqlite_unit_of_work_factory(read_only_database),
        now_ms=lambda: 1010,
    )
    claim_service = ClaimReadActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(read_only_database),
        now_ms=lambda: 1020,
    )

    save_service(
        SaveReadOnlyPlanCommand(
            command_id="save-stale",
            request_hash="9" * 64,
            plan_id="plan-stale",
            run_id="run-1",
            revision_no=1,
            summary_text="Stale",
            expected_run_version=0,
            actions=(
                ReadActionDraft(
                    action_id="action-stale",
                    position=1,
                    tool_name="calendar_get_event",
                    arguments={"calendar_id": "calendar-primary", "event_id": "event-focus"},
                    expected={"resource_type": "calendar_event"},
                    evidence_ids=("evidence-stale",),
                ),
            ),
            evidence=(
                ReadEvidenceDraft(
                    evidence_id="evidence-stale",
                    origin_type=EvidenceOriginType.DERIVED,
                    kind="USER_REQUEST",
                    excerpt="stale version",
                ),
            ),
        )
    )
    publish_service(
        PublishReadOnlyPlanCommand(
            command_id="publish-stale",
            request_hash="a1" * 32,
            plan_id="plan-stale",
            run_id="run-1",
            expected_run_version=0,
        )
    )

    response = claim_service(
        ClaimReadActionCommand(
            command_id="claim-stale",
            request_hash="b1" * 32,
            action_id="action-stale",
            expected_version=5,
        )
    )

    assert response.applied is False
    assert response.result_code == ResultCode.VERSION_CONFLICT.value
    assert fixture_gateway.call_log == []

    connection = connect_sqlite(read_only_database)
    try:
        row = connection.execute(
            "SELECT status, version FROM actions WHERE id = 'action-stale';"
        ).fetchone()
        receipt = connection.execute(
            """
            SELECT status, result_code
            FROM command_receipts
            WHERE command_id = 'claim-stale';
            """
        ).fetchone()
        assert row["status"] == "PROPOSED"
        assert row["version"] == 0
        assert receipt["status"] == "REJECTED"
        assert receipt["result_code"] == "VERSION_CONFLICT"
    finally:
        connection.close()


def test_received_receipts_can_resume_and_apply_save_publish_claim_complete_and_finalize(
    read_only_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    save_command = SaveReadOnlyPlanCommand(
        command_id="save-received",
        request_hash="c1" * 32,
        plan_id="plan-received",
        run_id="run-1",
        revision_no=1,
        summary_text="Resume all commands",
        expected_run_version=0,
        actions=(
            ReadActionDraft(
                action_id="action-received",
                position=1,
                tool_name="gmail_get_thread",
                arguments={"thread_id": "thread-project"},
                expected={"resource_type": "gmail_thread"},
                evidence_ids=("evidence-received",),
            ),
        ),
        evidence=(
            ReadEvidenceDraft(
                evidence_id="evidence-received",
                origin_type=EvidenceOriginType.DERIVED,
                kind="USER_REQUEST",
                excerpt="resume",
            ),
        ),
    )
    save_service = SaveReadOnlyPlanService(
        unit_of_work_factory=sqlite_unit_of_work_factory(read_only_database),
        now_ms=lambda: 1000,
    )
    _insert_received_receipt(
        read_only_database,
        command_id="save-received",
        command_type="SaveReadOnlyPlan",
        request_hash=save_command.request_hash,
        aggregate_type="Run",
        aggregate_id="run-1",
    )
    saved = save_service(save_command)
    assert saved.applied is True

    publish_command = PublishReadOnlyPlanCommand(
        command_id="publish-received",
        request_hash="c2" * 32,
        plan_id="plan-received",
        run_id="run-1",
        expected_run_version=0,
    )
    publish_service = PublishReadOnlyPlanService(
        unit_of_work_factory=sqlite_unit_of_work_factory(read_only_database),
        now_ms=lambda: 1010,
    )
    _insert_received_receipt(
        read_only_database,
        command_id="publish-received",
        command_type="PublishReadOnlyPlan",
        request_hash=publish_command.request_hash,
        aggregate_type="Run",
        aggregate_id="run-1",
    )
    published = publish_service(publish_command)
    assert published.applied is True

    claim_command = ClaimReadActionCommand(
        command_id="claim-received",
        request_hash="c3" * 32,
        action_id="action-received",
        expected_version=0,
    )
    claim_service = ClaimReadActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(read_only_database),
        now_ms=lambda: 1020,
    )
    _insert_received_receipt(
        read_only_database,
        command_id="claim-received",
        command_type="ClaimReadAction",
        request_hash=claim_command.request_hash,
        aggregate_type="Action",
        aggregate_id="action-received",
    )
    claimed = claim_service(claim_command)
    assert claimed.applied is True

    execute_service = ExecuteReadActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(read_only_database),
        gateway=fixture_gateway,
    )
    executed = execute_service(action_id="action-received")

    complete_command = CompleteReadActionCommand(
        command_id="complete-received",
        request_hash="c4" * 32,
        action_id="action-received",
        expected_version=1,
        output_json=executed.output_json,
        resource_refs=executed.resource_refs,
        evidence=executed.evidence,
    )
    complete_service = CompleteReadActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(read_only_database),
        now_ms=lambda: 1030,
    )
    _insert_received_receipt(
        read_only_database,
        command_id="complete-received",
        command_type="CompleteReadAction",
        request_hash=complete_command.request_hash,
        aggregate_type="Action",
        aggregate_id="action-received",
    )
    completed = complete_service(complete_command)
    assert completed.applied is True

    finalize_command = FinalizeReadActionCommand(
        command_id="finalize-received",
        request_hash="c5" * 32,
        action_id="action-received",
        expected_version=2,
    )
    finalize_service = FinalizeReadActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(read_only_database),
        now_ms=lambda: 1040,
    )
    _insert_received_receipt(
        read_only_database,
        command_id="finalize-received",
        command_type="FinalizeReadAction",
        request_hash=finalize_command.request_hash,
        aggregate_type="Action",
        aggregate_id="action-received",
    )
    finalized = finalize_service(finalize_command)
    assert finalized.applied is True

    connection = connect_sqlite(read_only_database)
    try:
        counts = connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM plans WHERE id = 'plan-received') AS plan_count,
                (SELECT COUNT(*) FROM actions WHERE id = 'action-received') AS action_count,
                (SELECT COUNT(*) FROM resource_refs) AS resource_count,
                (
                    SELECT COUNT(*)
                    FROM command_receipts
                    WHERE status = 'APPLIED'
                ) AS applied_receipts;
            """
        ).fetchone()
        assert tuple(counts) == (1, 1, 1, 5)
    finally:
        connection.close()


def test_received_receipts_recover_already_applied_complete_and_finalize_without_duplicates(
    read_only_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    test_read_only_happy_path_persists_projection_and_completes_run(
        read_only_database,
        fixture_gateway,
    )
    _reset_receipt_to_received(read_only_database, "complete-1")
    _reset_receipt_to_received(read_only_database, "finalize-1")

    complete_service = CompleteReadActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(read_only_database),
        now_ms=lambda: 2000,
    )
    complete_response = complete_service(
        CompleteReadActionCommand(
            command_id="complete-1",
            request_hash="d" * 64,
            action_id="action-1",
            expected_version=1,
            output_json='{"result_kind":"RESOURCE","resource_id":"thread-project"}',
            resource_refs=(
                CompletedResourceRef(
                    id="resource-ref-run-1-gmail_thread-thread-project",
                    source=ResourceSource.GMAIL,
                    resource_type=StoredResourceType.THREAD,
                    resource_id="thread-project",
                    parent_resource_id=None,
                    canonical_url=None,
                    title="Project sync follow-up",
                    event_time_ms=None,
                    version_token="3",
                    metadata_json='{"participant_count": 2, "subject": "Project sync follow-up"}',
                ),
            ),
            evidence=(
                CompletedEvidence(
                    id="evidence-run-1-gmail_thread-thread-project",
                    origin_type=EvidenceOriginType.GOOGLE_RESOURCE,
                    kind="GMAIL_THREAD",
                    excerpt="Need a draft for the Thursday recap.",
                    locator_json=None,
                    resource_ref_id="resource-ref-run-1-gmail_thread-thread-project",
                ),
            ),
        )
    )
    assert complete_response.applied is True

    finalize_service = FinalizeReadActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(read_only_database),
        now_ms=lambda: 2010,
    )
    finalize_response = finalize_service(
        FinalizeReadActionCommand(
            command_id="finalize-1",
            request_hash="e" * 64,
            action_id="action-1",
            expected_version=2,
        )
    )
    assert finalize_response.applied is True

    connection = connect_sqlite(read_only_database)
    try:
        counts = connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM resource_refs) AS resource_count,
                (SELECT COUNT(*) FROM evidence WHERE run_id = 'run-1') AS evidence_count,
                (SELECT version FROM actions WHERE id = 'action-1') AS action_version,
                (SELECT version FROM runs WHERE id = 'run-1') AS run_version;
            """
        ).fetchone()
        assert tuple(counts) == (1, 2, 3, 2)
    finally:
        connection.close()


def test_received_receipt_partial_complete_returns_recovery_required_without_more_rows(
    read_only_database: Path,
) -> None:
    _prepare_received_complete_partial_state(read_only_database)
    service = CompleteReadActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(read_only_database),
        now_ms=lambda: 2000,
    )
    response = service(
        CompleteReadActionCommand(
            command_id="complete-partial",
            request_hash="p1" * 32,
            action_id="action-partial",
            expected_version=1,
            output_json='{"result_kind":"RESOURCE","resource_id":"thread-project"}',
            resource_refs=(
                CompletedResourceRef(
                    id="resource-ref-run-1-gmail_thread-thread-project",
                    source=ResourceSource.GMAIL,
                    resource_type=StoredResourceType.THREAD,
                    resource_id="thread-project",
                    parent_resource_id=None,
                    canonical_url=None,
                    title="Project sync follow-up",
                    event_time_ms=None,
                    version_token="3",
                    metadata_json='{"participant_count":2,"subject":"Project sync follow-up"}',
                ),
            ),
            evidence=(),
        )
    )
    assert response.applied is False
    assert response.result_code == ResultCode.RECOVERY_REQUIRED.value

    connection = connect_sqlite(read_only_database)
    try:
        counts = connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM resource_refs) AS resource_count,
                (
                    SELECT COUNT(*)
                    FROM command_receipts
                    WHERE command_id = 'complete-partial'
                      AND status = 'REJECTED'
                ) AS rejected_receipt_count,
                (SELECT version FROM actions WHERE id = 'action-partial') AS action_version;
            """
        ).fetchone()
        assert tuple(counts) == (1, 1, 1)
    finally:
        connection.close()


def test_received_receipts_recover_already_applied_save_publish_and_claim(
    read_only_database: Path,
) -> None:
    save_command = SaveReadOnlyPlanCommand(
        command_id="save-applied",
        request_hash="s1" * 32,
        plan_id="plan-applied",
        run_id="run-1",
        revision_no=1,
        summary_text="save applied",
        expected_run_version=0,
        actions=(
            ReadActionDraft(
                action_id="action-applied",
                position=1,
                tool_name="gmail_get_thread",
                arguments={"thread_id": "thread-project"},
                expected={"resource_type": "gmail_thread"},
                evidence_ids=("evidence-applied",),
            ),
        ),
        evidence=(
            ReadEvidenceDraft(
                evidence_id="evidence-applied",
                origin_type=EvidenceOriginType.DERIVED,
                kind="USER_REQUEST",
                excerpt="save applied",
            ),
        ),
    )
    save_service = SaveReadOnlyPlanService(
        unit_of_work_factory=sqlite_unit_of_work_factory(read_only_database),
        now_ms=lambda: 1000,
    )
    save_service(save_command)
    _reset_receipt_to_received(read_only_database, "save-applied")

    saved = save_service(save_command)
    assert saved.applied is True

    publish_command = PublishReadOnlyPlanCommand(
        command_id="publish-applied",
        request_hash="s2" * 32,
        plan_id="plan-applied",
        run_id="run-1",
        expected_run_version=0,
    )
    publish_service = PublishReadOnlyPlanService(
        unit_of_work_factory=sqlite_unit_of_work_factory(read_only_database),
        now_ms=lambda: 1010,
    )
    publish_service(publish_command)
    _reset_receipt_to_received(read_only_database, "publish-applied")

    published = publish_service(publish_command)
    assert published.applied is True
    assert published.run_version == 1

    claim_command = ClaimReadActionCommand(
        command_id="claim-applied",
        request_hash="s3" * 32,
        action_id="action-applied",
        expected_version=0,
    )
    claim_service = ClaimReadActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(read_only_database),
        now_ms=lambda: 1020,
    )
    claim_service(claim_command)
    _reset_receipt_to_received(read_only_database, "claim-applied")

    claimed = claim_service(claim_command)
    assert claimed.applied is True
    assert claimed.action_status == "EXECUTING"
    assert claimed.action_version == 1

    connection = connect_sqlite(read_only_database)
    try:
        counts = connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM plans WHERE id = 'plan-applied') AS plan_count,
                (SELECT COUNT(*) FROM actions WHERE id = 'action-applied') AS action_count,
                (SELECT version FROM actions WHERE id = 'action-applied') AS action_version,
                (SELECT version FROM runs WHERE id = 'run-1') AS run_version;
            """
        ).fetchone()
        assert tuple(counts) == (1, 1, 1, 1)
    finally:
        connection.close()


def test_received_receipts_can_resume_and_recover_fail(
    read_only_database: Path,
) -> None:
    _prepare_fail_action_state(
        read_only_database, action_id="action-fail-received", plan_id="plan-fail-received"
    )
    fail_command = FailReadActionCommand(
        command_id="fail-received",
        request_hash="f1" * 32,
        action_id="action-fail-received",
        expected_version=1,
        safe_error_code="UPSTREAM_5XX",
        retryable=True,
        safe_error_detail="timeout",
    )
    fail_service = FailReadActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(read_only_database),
        now_ms=lambda: 2000,
    )
    _insert_received_receipt(
        read_only_database,
        command_id="fail-received",
        command_type="FailReadAction",
        request_hash=fail_command.request_hash,
        aggregate_type="Action",
        aggregate_id="action-fail-received",
    )
    first = fail_service(fail_command)
    assert first.applied is True
    assert first.action_status == "FAILED"

    _reset_receipt_to_received(read_only_database, "fail-received")
    second = fail_service(fail_command)
    assert second.applied is True
    assert second.action_status == "FAILED"

    connection = connect_sqlite(read_only_database)
    try:
        counts = connection.execute(
            """
            SELECT
                (SELECT version FROM actions WHERE id = 'action-fail-received') AS action_version,
                (
                    SELECT COUNT(*)
                    FROM trace_events
                    WHERE action_id = 'action-fail-received'
                      AND event_type = 'READ_ACTION_FAILED'
                ) AS trace_count,
                (SELECT COUNT(*) FROM approvals) AS approval_count,
                (SELECT COUNT(*) FROM execution_attempts) AS attempt_count,
                (SELECT COUNT(*) FROM verifications) AS verification_count;
            """
        ).fetchone()
        assert tuple(counts) == (2, 1, 0, 0, 0)
    finally:
        connection.close()


def _insert_received_receipt(
    database_path: Path,
    *,
    command_id: str,
    command_type: str,
    request_hash: str,
    aggregate_type: str,
    aggregate_id: str,
) -> None:
    connection = connect_sqlite(database_path)
    try:
        connection.execute(
            """
            INSERT INTO command_receipts (
                command_id, command_type, request_hash, aggregate_type, aggregate_id,
                status, created_at_ms
            )
            VALUES (?, ?, ?, ?, ?, 'RECEIVED', 999);
            """,
            (command_id, command_type, request_hash, aggregate_type, aggregate_id),
        )
    finally:
        connection.close()


def _reset_receipt_to_received(database_path: Path, command_id: str) -> None:
    connection = connect_sqlite(database_path)
    try:
        connection.execute(
            """
            UPDATE command_receipts
            SET status = 'RECEIVED',
                result_code = NULL,
                result_version = NULL,
                response_json = NULL,
                completed_at_ms = NULL
            WHERE command_id = ?;
            """,
            (command_id,),
        )
    finally:
        connection.close()


def _prepare_received_complete_partial_state(database_path: Path) -> None:
    save_service = SaveReadOnlyPlanService(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        now_ms=lambda: 1000,
    )
    publish_service = PublishReadOnlyPlanService(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        now_ms=lambda: 1010,
    )
    claim_service = ClaimReadActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        now_ms=lambda: 1020,
    )
    save_service(
        SaveReadOnlyPlanCommand(
            command_id="save-partial",
            request_hash="p2" * 32,
            plan_id="plan-partial",
            run_id="run-1",
            revision_no=1,
            summary_text="partial",
            expected_run_version=0,
            actions=(
                ReadActionDraft(
                    action_id="action-partial",
                    position=1,
                    tool_name="gmail_get_thread",
                    arguments={"thread_id": "thread-project"},
                    expected={"resource_type": "gmail_thread"},
                    evidence_ids=("evidence-partial",),
                ),
            ),
            evidence=(
                ReadEvidenceDraft(
                    evidence_id="evidence-partial",
                    origin_type=EvidenceOriginType.DERIVED,
                    kind="USER_REQUEST",
                    excerpt="partial",
                ),
            ),
        )
    )
    publish_service(
        PublishReadOnlyPlanCommand(
            command_id="publish-partial",
            request_hash="p3" * 32,
            plan_id="plan-partial",
            run_id="run-1",
            expected_run_version=0,
        )
    )
    claim_service(
        ClaimReadActionCommand(
            command_id="claim-partial",
            request_hash="p4" * 32,
            action_id="action-partial",
            expected_version=0,
        )
    )
    connection = connect_sqlite(database_path)
    try:
        connection.execute(
            """
            INSERT INTO resource_refs (
                id, run_id, source, resource_type, resource_id, parent_resource_id,
                canonical_url, title, event_time_ms, version_token, metadata_json, captured_at_ms
            )
            VALUES (
                'resource-ref-run-1-gmail_thread-thread-project',
                'run-1', 'GMAIL', 'THREAD', 'thread-project', NULL,
                NULL, 'Project sync follow-up', NULL, '3',
                '{"participant_count":2,"subject":"Project sync follow-up"}', 1030
            );
            """
        )
        connection.execute(
            """
            INSERT INTO command_receipts (
                command_id, command_type, request_hash, aggregate_type, aggregate_id,
                status, created_at_ms
            )
            VALUES (
                'complete-partial', 'CompleteReadAction', ?, 'Action', 'action-partial',
                'RECEIVED', 1030
            );
            """,
            ("p1" * 32,),
        )
    finally:
        connection.close()


def _prepare_fail_action_state(database_path: Path, *, action_id: str, plan_id: str) -> None:
    save_service = SaveReadOnlyPlanService(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        now_ms=lambda: 1000,
    )
    publish_service = PublishReadOnlyPlanService(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        now_ms=lambda: 1010,
    )
    claim_service = ClaimReadActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        now_ms=lambda: 1020,
    )
    save_service(
        SaveReadOnlyPlanCommand(
            command_id=f"save-{plan_id}",
            request_hash="fa" * 32,
            plan_id=plan_id,
            run_id="run-1",
            revision_no=1,
            summary_text="fail prep",
            expected_run_version=0,
            actions=(
                ReadActionDraft(
                    action_id=action_id,
                    position=1,
                    tool_name="gmail_get_thread",
                    arguments={"thread_id": "thread-project"},
                    expected={"resource_type": "gmail_thread"},
                    evidence_ids=(f"evidence-{plan_id}",),
                ),
            ),
            evidence=(
                ReadEvidenceDraft(
                    evidence_id=f"evidence-{plan_id}",
                    origin_type=EvidenceOriginType.DERIVED,
                    kind="USER_REQUEST",
                    excerpt="fail prep",
                ),
            ),
        )
    )
    publish_service(
        PublishReadOnlyPlanCommand(
            command_id=f"publish-{plan_id}",
            request_hash="fb" * 32,
            plan_id=plan_id,
            run_id="run-1",
            expected_run_version=0,
        )
    )
    claim_service(
        ClaimReadActionCommand(
            command_id=f"claim-{plan_id}",
            request_hash="fc" * 32,
            action_id=action_id,
            expected_version=0,
        )
    )
