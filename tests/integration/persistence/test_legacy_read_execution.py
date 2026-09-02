from pathlib import Path
from typing import cast

from google_work_agent.adapters.connectors.google.workspace.composition import (
    GOOGLE_WORKSPACE_CONNECTOR_ID,
)
from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.migration import apply_migrations
from google_work_agent.adapters.persistence.sqlite.unit_of_work import (
    sqlite_unit_of_work_factory,
)
from google_work_agent.application.use_cases.action.claim_read_action import (
    ClaimReadActionHandler,
)
from google_work_agent.application.use_cases.action.complete_read_action import (
    CompleteReadActionHandler,
)
from google_work_agent.application.use_cases.action.finalize_read_action import (
    FinalizeReadActionHandler,
)
from google_work_agent.application.use_cases.action.read_contracts import (
    ClaimReadActionCommand,
    CompleteReadActionCommand,
    FinalizeReadActionCommand,
    PublishReadOnlyPlanCommand,
    ReadActionDraft,
    ReadEvidenceDraft,
    SaveReadOnlyPlanCommand,
)
from google_work_agent.application.use_cases.plan.publish_read_only_plan import (
    PublishReadOnlyPlanHandler,
)
from google_work_agent.application.use_cases.plan.record_review_result import (
    RecordReviewResultCommandV1,
    RecordReviewResultHandler,
)
from google_work_agent.application.use_cases.resource.connector_read_projection import (
    ConnectorReadProjection,
)
from google_work_agent.domain.evidence.model import EvidenceOriginType
from tests.support.fakes import FakeGoogleGateway
from tests.support.fixtures import ProductFixtureSnapshotLoader

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "data" / "google"


def test_fresh_legacy_read__reaches_connector_and__closes_without_write_facts(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "legacy-read.db"
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

    unit_of_work_factory = sqlite_unit_of_work_factory(database_path)
    plan_service = PublishReadOnlyPlanHandler(
        unit_of_work_factory=unit_of_work_factory,
        now_ms=lambda: 1000,
    )
    claim_service = ClaimReadActionHandler(
        unit_of_work_factory=unit_of_work_factory,
        now_ms=lambda: 1020,
    )
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot(
        "workspace/product_fixture_v1.json"
    )
    gateway = FakeGoogleGateway(snapshot)
    execute_service = CompleteReadActionHandler(
        unit_of_work_factory=unit_of_work_factory,
        gateway=cast(ConnectorReadProjection, gateway),
    )
    complete_service = CompleteReadActionHandler(
        unit_of_work_factory=unit_of_work_factory,
        now_ms=lambda: 1030,
    )
    finalize_service = FinalizeReadActionHandler(
        unit_of_work_factory=unit_of_work_factory,
        now_ms=lambda: 1040,
    )

    saved = plan_service(
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
                    connector_id=GOOGLE_WORKSPACE_CONNECTOR_ID,
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
    with unit_of_work_factory() as unit_of_work:
        bundle = unit_of_work.plans.load_bundle("plan-1")
        assert bundle is not None
    review = RecordReviewResultHandler(
        unit_of_work_factory=unit_of_work_factory,
        now_ms=lambda: 1005,
    )(
        RecordReviewResultCommandV1(
            command_id="review-pass-plan-1",
            plan_id="plan-1",
            expected_plan_version=bundle.plan.revision_no,
            expected_review_version=bundle.plan.review_version,
            review_artifact_id="review-artifact-plan-1",
            review_version=bundle.plan.review_version,
            disposition="PASS",
            based_on_action_versions={action.id: action.version for action in bundle.actions},
        )
    )
    assert review.applied is True

    published = plan_service(
        PublishReadOnlyPlanCommand(
            command_id="publish-1",
            request_hash="b" * 64,
            plan_id="plan-1",
            run_id="run-1",
            expected_run_version=0,
        )
    )
    assert published.applied is True
    assert published.run_status == "EXECUTING"

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

    executed = execute_service.execute(action_id="action-1")
    assert gateway.call_log[-1].operation == "get_gmail_thread"

    completed = complete_service(
        CompleteReadActionCommand(
            command_id="complete-1",
            request_hash="d" * 64,
            action_id="action-1",
            expected_version=claimed.action_version,
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
            expected_version=completed.action_version,
        )
    )
    assert finalized.applied is True
    assert finalized.action_status == "VERIFIED"
    assert finalized.plan_completed is True
    assert finalized.run_completed is True

    connection = connect_sqlite(database_path)
    try:
        run = connection.execute(
            "SELECT status, terminal_result_kind FROM runs WHERE id = 'run-1';"
        ).fetchone()
        plan = connection.execute("SELECT status FROM plans WHERE id = 'plan-1';").fetchone()
        counts = connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM approvals) AS approval_count,
                (SELECT COUNT(*) FROM execution_attempts) AS attempt_count,
                (SELECT COUNT(*) FROM verifications) AS verification_count,
                (SELECT COUNT(*) FROM messages
                 WHERE run_id = 'run-1' AND role = 'ASSISTANT') AS final_message_count;
            """
        ).fetchone()
        assert run["status"] == "COMPLETED"
        assert run["terminal_result_kind"] == "SUCCESS"
        assert plan["status"] == "COMPLETED"
        assert tuple(counts) == (0, 0, 0, 1)
    finally:
        connection.close()
