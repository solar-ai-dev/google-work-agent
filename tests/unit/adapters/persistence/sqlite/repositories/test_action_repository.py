import sqlite3

from google_work_agent.adapters.persistence.sqlite.repositories.action_repository import (
    SqliteActionRepository,
)
from google_work_agent.domain.action.model import Action, ActionStatusV1


def _action(action_id: str, position: int, status: ActionStatusV1) -> Action:
    return Action(
        id=action_id,
        plan_id="plan-1",
        connector_id="google_workspace",
        position=position,
        tool_name="tasks_create_task",
        effect_type="CREATE",
        approval_requirement="REQUIRED",
        verification_policy="GET_COMPARE",
        recovery_policy="RESOURCE_SEARCH",
        target_resource_ref_id=None,
        status=status.value,
        arguments_json="{}",
        arguments_hash="a" * 64,
        expected_json="{}",
        risk={},
        version=0,
        created_at_ms=1,
        updated_at_ms=1,
    )


def test_action_repository_owns_dependency_storage_and_readiness() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """CREATE TABLE actions (
            id TEXT PRIMARY KEY, plan_id TEXT, connector_id TEXT, position INTEGER,
            tool_name TEXT, effect_type TEXT, approval_requirement TEXT,
            verification_policy TEXT, recovery_policy TEXT,
            target_resource_ref_id TEXT, status TEXT, arguments_json TEXT,
            arguments_hash TEXT, expected_json TEXT, risk_json TEXT, version INTEGER,
            created_at_ms INTEGER, updated_at_ms INTEGER
        );
        CREATE TABLE action_dependencies (
            action_id TEXT, depends_on_action_id TEXT,
            PRIMARY KEY (action_id, depends_on_action_id)
        );
        CREATE TABLE action_evidence (
            action_id TEXT, evidence_id TEXT,
            PRIMARY KEY (action_id, evidence_id)
        );
        """
    )
    repository = SqliteActionRepository(connection)
    repository.insert_for_plan(_action("action-1", 1, ActionStatusV1.APPROVED))
    repository.insert_for_plan(
        _action("action-2", 2, ActionStatusV1.APPROVED),
        dependency_ids=("action-1",),
    )

    assert repository.list_dependents("action-1") == ("action-2",)
    assert not repository.is_dependency_ready("action-2")
    assert repository.update_if_version_and_status(
        "action-1",
        0,
        frozenset({ActionStatusV1.APPROVED}),
        {"status": ActionStatusV1.VERIFIED, "version": 1},
    )
    assert repository.is_dependency_ready("action-2")
    assert [item.id for item in repository.list_for_plan("plan-1")] == [
        "action-1",
        "action-2",
    ]
