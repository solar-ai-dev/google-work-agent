from pathlib import Path

from google_work_agent.adapters.langgraph.connector_read_result import (
    ConnectorBoundCompleteReadActionService,
)
from google_work_agent.adapters.persistence import apply_migrations, connect_sqlite
from google_work_agent.adapters.persistence.connector_identity import (
    bind_action_connector_ids,
    bind_resource_connector_id,
)
from google_work_agent.adapters.persistence.unit_of_work import (
    SQLiteUnitOfWork,
    sqlite_unit_of_work_factory,
)
from google_work_agent.application.read_contracts import (
    CompleteReadActionCommand,
    CompletedResourceRef,
)
from google_work_agent.application.read_lifecycle import CompleteReadActionService
from google_work_agent.ports import (
    ActionRecord,
    ResourceRefRecord,
    ResourceSource,
    StoredResourceType,
)


def _seed_plan(database_path: Path) -> None:
    connection = connect_sqlite(database_path)
    try:
        apply_migrations(connection, now_ms=lambda: 1)
        connection.execute(
            "INSERT INTO google_accounts VALUES ('account-1', 'u@example.com', NULL, 1, NULL);"
        )
        connection.execute(
            "INSERT INTO conversations VALUES ('conversation-1', 'account-1', 'Test', 1, 1);"
        )
        connection.execute(
            """
            INSERT INTO runs (
                id, conversation_id, entry_mode, status, langgraph_thread_id,
                requested_mode, budget_json, version, started_at_ms
            ) VALUES ('run-1', 'conversation-1', 'AGENT_SEARCH', 'PLANNING',
                      'thread-1', 'AUTO', '{}', 0, 1);
            """
        )
        connection.execute(
            """
            INSERT INTO plans (
                id, run_id, revision_no, status, created_at_ms, review_status, review_version
            ) VALUES ('plan-1', 'run-1', 1, 'DRAFT', 1, 'PASSED', 0);
            """
        )
        connection.commit()
    finally:
        connection.close()


def test_action_and_resource_ref_use_explicit_frozen_connector_binding(tmp_path: Path) -> None:
    database_path = tmp_path / "connector-binding.db"
    _seed_plan(database_path)

    action = ActionRecord(
        id="action-1",
        plan_id="plan-1",
        position=1,
        tool_name="github_create_issue",
        effect_type="CREATE",
        approval_requirement="REQUIRED",
        verification_policy="GET_COMPARE",
        recovery_policy="RESOURCE_SEARCH",
        target_resource_ref_id=None,
        status="PROPOSED",
        arguments_json='{"title":"Issue"}',
        arguments_hash="a" * 64,
        expected_json="{}",
        risk={},
        version=0,
        created_at_ms=2,
        updated_at_ms=2,
    )
    resource_ref = ResourceRefRecord(
        id="resource-ref-1",
        run_id="run-1",
        source=ResourceSource.TASKS,
        resource_type=StoredResourceType.TASK,
        resource_id="issue-1",
        parent_resource_id=None,
        canonical_url=None,
        title="Issue",
        event_time_ms=None,
        version_token="v1",
        metadata_json="{}",
        captured_at_ms=3,
    )

    with bind_action_connector_ids({"action-1": "github"}):
        with SQLiteUnitOfWork(database_path) as unit_of_work:
            unit_of_work.actions.insert_write_action(action)
            unit_of_work.commit()

    with bind_resource_connector_id("github"):
        with SQLiteUnitOfWork(database_path) as unit_of_work:
            unit_of_work.resource_refs.upsert(resource_ref)
            persisted = unit_of_work.resource_refs.get_by_unique_key(
                run_id="run-1",
                source=ResourceSource.TASKS.value,
                resource_type=StoredResourceType.TASK.value,
                resource_id="issue-1",
            )
            assert persisted is not None
            assert persisted.id == "resource-ref-1"
            unit_of_work.commit()

    connection = connect_sqlite(database_path)
    try:
        assert connection.execute(
            "SELECT connector_id FROM actions WHERE id = 'action-1';"
        ).fetchone()[0] == "github"
        assert connection.execute(
            "SELECT connector_id FROM resource_refs WHERE id = 'resource-ref-1';"
        ).fetchone()[0] == "github"
        assert connection.execute("PRAGMA foreign_key_check;").fetchall() == []
    finally:
        connection.close()


def test_read_action_and_completion_resource_keep_same_connector(tmp_path: Path) -> None:
    database_path = tmp_path / "read-connector-binding.db"
    _seed_plan(database_path)

    action = ActionRecord(
        id="read-action-1",
        plan_id="plan-1",
        position=1,
        tool_name="tasks_list_tasks",
        effect_type="READ",
        approval_requirement="NONE",
        verification_policy="NONE",
        recovery_policy="NONE",
        target_resource_ref_id=None,
        status="EXECUTING",
        arguments_json='{"task_list_id":"list-1"}',
        arguments_hash="b" * 64,
        expected_json="{}",
        risk={},
        version=0,
        created_at_ms=2,
        updated_at_ms=2,
    )
    with bind_action_connector_ids({"read-action-1": "github"}):
        with SQLiteUnitOfWork(database_path) as unit_of_work:
            unit_of_work.actions.insert_read_action(action)
            unit_of_work.commit()

    factory = sqlite_unit_of_work_factory(database_path)
    delegate = CompleteReadActionService(unit_of_work_factory=factory, now_ms=lambda: 3)
    service = ConnectorBoundCompleteReadActionService(
        delegate=delegate,
        unit_of_work_factory=factory,
    )
    response = service(
        CompleteReadActionCommand(
            command_id="complete-read-1",
            request_hash="r1" * 32,
            action_id="read-action-1",
            expected_version=0,
            output_json="{}",
            resource_refs=(
                CompletedResourceRef(
                    id="read-resource-1",
                    source=ResourceSource.TASKS,
                    resource_type=StoredResourceType.TASK,
                    resource_id="issue-2",
                    parent_resource_id="list-1",
                    canonical_url=None,
                    title="Issue 2",
                    event_time_ms=None,
                    version_token="v2",
                    metadata_json="{}",
                ),
            ),
            evidence=(),
        )
    )
    assert response.applied is True

    connection = connect_sqlite(database_path)
    try:
        assert connection.execute(
            "SELECT connector_id FROM actions WHERE id = 'read-action-1';"
        ).fetchone()[0] == "github"
        assert connection.execute(
            "SELECT connector_id FROM resource_refs WHERE id = 'read-resource-1';"
        ).fetchone()[0] == "github"
        assert connection.execute("PRAGMA foreign_key_check;").fetchall() == []
    finally:
        connection.close()
