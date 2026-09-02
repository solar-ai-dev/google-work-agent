from pathlib import Path
from typing import cast

import pytest

from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.migration import apply_migrations
from google_work_agent.adapters.persistence.sqlite.unit_of_work import (
    SqliteUnitOfWork,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_development_tool_registry,
)
from google_work_agent.application.use_cases.resource_ref.persist_resource_ref import (
    persist_registered_resource_ref,
)
from google_work_agent.domain.action.model import Action as ActionRecord
from google_work_agent.domain.resource_ref.model import ResourceRef as ResourceRefRecord
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork

_TOOL_REGISTRY = load_development_tool_registry()


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
            ) VALUES ('plan-1', 'run-1', 1, 'ACTIVE', 1, 'REQUIRED', 0);
            """
        )
        connection.commit()
    finally:
        connection.close()


def test_action_and__resource_ref_use__explicit_connector_identity(tmp_path: Path) -> None:
    database_path = tmp_path / "connector-binding.db"
    _seed_plan(database_path)

    action = ActionRecord(
        id="action-1",
        plan_id="plan-1",
        connector_id="google_workspace",
        position=1,
        tool_name="tasks_create_task",
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
        connector_id="google_workspace",
        resource_type="task",
        resource_id="issue-1",
        parent_resource_id=None,
        canonical_url=None,
        title="Issue",
        event_time_ms=None,
        version_token="v1",
        metadata_json="{}",
        captured_at_ms=3,
    )

    with SqliteUnitOfWork(database_path) as unit_of_work:
        unit_of_work.actions.insert_for_plan(action)
        persisted = unit_of_work.resource_refs.upsert_bound_ref(resource_ref)
        assert persisted is not None
        assert persisted.id == "resource-ref-1"
        unit_of_work.commit()

    connection = connect_sqlite(database_path)
    try:
        assert (
            connection.execute(
                "SELECT connector_id FROM actions WHERE id = 'action-1';"
            ).fetchone()[0]
            == "google_workspace"
        )
        assert (
            connection.execute(
                "SELECT connector_id FROM resource_refs WHERE id = 'resource-ref-1';"
            ).fetchone()[0]
            == "google_workspace"
        )
        assert connection.execute("PRAGMA foreign_key_check;").fetchall() == []
    finally:
        connection.close()


def test_unregistered_resource__connector_is__rejected_before_persistence(tmp_path: Path) -> None:
    database_path = tmp_path / "unregistered-connector.db"
    _seed_plan(database_path)
    resource_ref = ResourceRefRecord(
        id="unregistered-ref",
        run_id="run-1",
        connector_id="github",
        resource_type="task",
        resource_id="issue-1",
        parent_resource_id=None,
        canonical_url=None,
        title="Issue",
        event_time_ms=None,
        version_token="v1",
        metadata_json="{}",
        captured_at_ms=3,
    )
    with (
        SqliteUnitOfWork(database_path) as unit_of_work,
        pytest.raises(LookupError, match="connector/resource type is not registered"),
    ):
        persist_registered_resource_ref(
            cast(UnitOfWork, unit_of_work),
            resource_ref,
            catalog=_TOOL_REGISTRY,
        )
