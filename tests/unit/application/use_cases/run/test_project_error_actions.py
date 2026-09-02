from __future__ import annotations

from pathlib import Path

from tests.support.checkpoint import sqlite_checkpoint

from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.migration import apply_migrations
from google_work_agent.adapters.persistence.sqlite.unit_of_work import sqlite_unit_of_work_factory
from google_work_agent.application.use_cases.run.get_run_snapshot import (
    GetRunSnapshotHandler,
    GetRunSnapshotQuery,
)
from google_work_agent.application.use_cases.run.project_error_actions import (
    ProjectErrorActionsHandler,
    ProjectErrorActionsQueryV1,
)


class _Registry:
    def validate_resume_target(self, *_args: object, **_kwargs: object) -> bool:
        return False


def _database(tmp_path: Path, *, delivery_certainty: str) -> Path:
    path = tmp_path / f"error-{delivery_certainty}.db"
    with connect_sqlite(path) as connection:
        apply_migrations(connection)
        connection.execute(
            "INSERT INTO google_accounts (id, email, connected_at_ms) "
            "VALUES ('account-1', 'u@example.com', 1)"
        )
        connection.execute(
            "INSERT INTO conversations VALUES ('conversation-1', 'account-1', 'Inbox', 1, 1)"
        )
        connection.execute(
            """INSERT INTO runs (
                id, conversation_id, entry_mode, status, langgraph_thread_id,
                requested_mode, budget_json, version, started_at_ms
            ) VALUES ('run-1', 'conversation-1', 'AGENT_SEARCH', 'WAITING_APPROVAL',
                      'thread-1', 'AUTO', '{}', 4, 1)"""
        )
        connection.execute(
            """INSERT INTO plans (
                id, run_id, revision_no, status, summary_text, created_at_ms,
                review_status, review_version, review_disposition
            ) VALUES ('plan-1', 'run-1', 1, 'WAITING_APPROVAL', 'Plan', 2,
                      'PASSED', 1, 'PASS')"""
        )
        connection.execute(
            """INSERT INTO actions (
                id, plan_id, connector_id, position, tool_name, effect_type,
                approval_requirement, verification_policy, recovery_policy, status,
                arguments_json, arguments_hash, expected_json, created_at_ms, updated_at_ms
            ) VALUES ('action-1', 'plan-1', 'google_workspace', 1, 'tasks_create_task',
                      'CREATE', 'REQUIRED', 'GET_COMPARE', 'RESOURCE_SEARCH', 'FAILED',
                      '{}', ?, '{}', 3, 3)""",
            ("a" * 64,),
        )
        connection.execute(
            """INSERT INTO approvals (
                id, action_id, approval_no, action_version, status,
                approved_by_account_id, arguments_snapshot_json,
                canonical_arguments_hash, source_snapshot_json, source_snapshot_hash,
                policy_version, tool_schema_version, idempotency_key,
                recovery_fingerprint, approved_at_ms, expires_at_ms, consumed_at_ms
            ) VALUES ('approval-1', 'action-1', 1, 0, 'CONSUMED', 'account-1',
                      '{}', ?, '{}', ?, 'p1', 's1', ?, ?, 3, 100, 4)""",
            ("b" * 64, "c" * 64, "d" * 64, "e" * 64),
        )
        connection.execute(
            """INSERT INTO execution_attempts (
                id, approval_id, attempt_no, status, version,
                response_metadata_json, started_at_ms, finished_at_ms
            ) VALUES ('attempt-1', 'approval-1', 1, 'FAILED', 1, ?, 4, 5)""",
            (f'{{"delivery_certainty":"{delivery_certainty}"}}',),
        )
        connection.execute(
            """INSERT INTO audit_events (
                run_id, action_id, actor_type, actor_id, event_type, outcome,
                metadata_json, created_at_ms
            ) VALUES ('run-1', 'action-1', 'AGENT', 'claim_execution',
                      'EXECUTION_CLAIMED', 'TRANSITION_APPLIED',
                      '{"attempt_id":"attempt-1"}', 4)"""
        )
        connection.execute("UPDATE runs SET status = 'FAILED' WHERE id = 'run-1'")
    return path


def _project(path: Path):  # type: ignore[no-untyped-def]
    return ProjectErrorActionsHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(path),
        checkpoint_port=sqlite_checkpoint(path),
        resume_target_registry=_Registry(),  # type: ignore[arg-type]
    )(ProjectErrorActionsQueryV1("run-1"))


def test_retry_is_available__only_for_latest__not_sent_failure(tmp_path: Path) -> None:
    retryable = _project(_database(tmp_path, delivery_certainty="NOT_SENT"))
    unsafe = _project(_database(tmp_path, delivery_certainty="UNKNOWN_RESULT"))

    assert retryable is not None
    assert [item.kind for item in retryable.actions] == [
        "PREPARE_RETRY",
        "OPEN_DIAGNOSTICS",
    ]
    assert retryable.actions[0].action_id == "action-1"
    assert unsafe is not None
    assert [item.kind for item in unsafe.actions] == ["OPEN_DIAGNOSTICS"]


def test_run_snapshot__projects_latest__delivery_certainty(tmp_path: Path) -> None:
    result = GetRunSnapshotHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(
            _database(tmp_path, delivery_certainty="NOT_SENT")
        )
    )(GetRunSnapshotQuery("run-1"))

    assert result is not None
    assert result.actions[0].delivery_certainty == "NOT_SENT"
