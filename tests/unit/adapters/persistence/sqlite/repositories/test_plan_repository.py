from pathlib import Path

from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.migration import apply_migrations
from google_work_agent.adapters.persistence.sqlite.repositories.plan_repository import (
    SqlitePlanRepository,
)
from google_work_agent.domain.plan.model import Plan, PlanReviewStatus, PlanStatusV1


def test_plan_repository_exact__revision_review_and__status_cas_surface(tmp_path: Path) -> None:
    connection = connect_sqlite(tmp_path / "plan-repository.db")
    apply_migrations(connection, now_ms=lambda: 1)
    connection.execute(
        "INSERT INTO google_accounts VALUES ('account-1', 'u@example.com', NULL, 1, NULL);"
    )
    connection.execute(
        "INSERT INTO conversations VALUES ('conversation-1', 'account-1', 'Test', 1, 1);"
    )
    connection.execute(
        """INSERT INTO runs (
               id, conversation_id, entry_mode, status, langgraph_thread_id,
               requested_mode, budget_json, version, started_at_ms
           ) VALUES ('run-1', 'conversation-1', 'AGENT_SEARCH', 'PLANNING',
                     'thread-1', 'AUTO', '{}', 0, 1);"""
    )
    repository = SqlitePlanRepository(connection)
    repository.insert_revision(
        Plan(
            id="plan-1",
            run_id="run-1",
            revision_no=1,
            status=PlanStatusV1.DRAFT,
            summary_text="draft",
            created_at_ms=1,
        )
    )
    connection.execute(
        """INSERT INTO evidence (
               id, run_id, origin_type, kind, excerpt, created_at_ms
           ) VALUES ('evidence-1', 'run-1', 'DERIVED', 'FACT', 'fact', 2);"""
    )
    for action_id, position in (("action-1", 1), ("action-2", 2)):
        connection.execute(
            """INSERT INTO actions (
                   id, plan_id, connector_id, position, tool_name, effect_type,
                   approval_requirement, verification_policy, recovery_policy,
                   status, arguments_json, arguments_hash, expected_json,
                   risk_json, version, created_at_ms, updated_at_ms
               ) VALUES (?, 'plan-1', 'google_workspace', ?, 'tasks_create_task',
                         'CREATE', 'REQUIRED', 'GET_COMPARE', 'RESOURCE_SEARCH',
                         'PROPOSED', '{}', ?, '{}', '{}', 0, 2, 2);""",
            (action_id, position, action_id[-1] * 64),
        )
    connection.execute("INSERT INTO action_dependencies VALUES ('action-2', 'action-1');")
    connection.execute("INSERT INTO action_evidence VALUES ('action-1', 'evidence-1');")

    statements: list[str] = []
    connection.set_trace_callback(statements.append)
    bundle = repository.load_bundle("plan-1")
    connection.set_trace_callback(None)
    assert bundle is not None
    assert repository.get_current("run-1") == bundle.plan
    assert [action.id for action in bundle.actions] == ["action-1", "action-2"]
    assert [(item.action_id, item.depends_on_action_id) for item in bundle.dependencies] == [
        ("action-2", "action-1")
    ]
    assert [item.id for item in bundle.evidence] == ["evidence-1"]
    assert [(item.action_id, item.evidence_id) for item in bundle.action_evidence] == [
        ("action-1", "evidence-1")
    ]
    assert len([sql for sql in statements if sql.lstrip().upper().startswith("SELECT")]) == 4
    reviewed = repository.record_review_result(
        "plan-1",
        expected_review_version=0,
        expected_review_statuses=frozenset({PlanReviewStatus.REQUIRED}),
        values={
            "review_status": PlanReviewStatus.REQUIRED,
            "review_version": 1,
            "review_disposition": "REVISE",
        },
    )
    assert reviewed is not None and reviewed.review_version == 1
    assert repository.update_if_version_and_status(
        "plan-1",
        1,
        frozenset({PlanStatusV1.DRAFT}),
        {"status": PlanStatusV1.ACTIVE},
    )
