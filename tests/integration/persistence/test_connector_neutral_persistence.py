import shutil
import sqlite3
from pathlib import Path

from google_work_agent.adapters.persistence import apply_migrations, connect_sqlite

RUNTIME_MIGRATIONS_DIR = Path("src/google_work_agent/adapters/persistence/migrations")


def test_connector_neutral_migration_preserves_populated_execution_history(tmp_path: Path) -> None:
    upgrade_dir = tmp_path / "upgrade-migrations"
    upgrade_dir.mkdir()
    for version in range(1, 7):
        source = next(RUNTIME_MIGRATIONS_DIR.glob(f"{version:04d}_*.sql"))
        shutil.copyfile(source, upgrade_dir / source.name)

    connection = connect_sqlite(tmp_path / "connector-upgrade.db")
    try:
        apply_migrations(connection, migrations_dir=upgrade_dir, now_ms=lambda: 1)
        _seed_populated_google_history(connection)
        before = _history_counts(connection)

        source = RUNTIME_MIGRATIONS_DIR / "0007_connector_neutral_persistence.sql"
        shutil.copyfile(source, upgrade_dir / source.name)
        results = apply_migrations(connection, migrations_dir=upgrade_dir, now_ms=lambda: 2)

        assert [result.applied for result in results] == [
            False,
            False,
            False,
            False,
            False,
            False,
            True,
        ]
        assert _history_counts(connection) == before
        resource_ref = connection.execute(
            """
            SELECT connector_id, source, resource_type, resource_id, version_token, metadata_json
            FROM resource_refs WHERE id = 'resource-google';
            """
        ).fetchone()
        assert tuple(resource_ref) == (
            "google_workspace",
            "TASKS",
            "TASK",
            "shared-task-id",
            "version-1",
            '{"status":"needsAction"}',
        )
        action = connection.execute(
            "SELECT connector_id, tool_name, target_resource_ref_id FROM actions WHERE id = 'action-1';"
        ).fetchone()
        assert tuple(action) == ("google_workspace", "tasks_update_task", "resource-google")
        links = connection.execute(
            """
            SELECT ea.approval_id, ea.result_resource_ref_id, v.execution_attempt_id
            FROM execution_attempts AS ea
            JOIN verifications AS v ON v.execution_attempt_id = ea.id
            WHERE ea.id = 'attempt-1';
            """
        ).fetchone()
        assert tuple(links) == ("approval-1", "resource-google", "attempt-1")
        assert connection.execute("PRAGMA foreign_key_check;").fetchall() == []
    finally:
        connection.close()


def test_connector_identity_allows_same_canonical_task_id_across_connectors(tmp_path: Path) -> None:
    connection = connect_sqlite(tmp_path / "connector-coexist.db")
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
            INSERT INTO resource_refs (
                id, run_id, connector_id, source, resource_type, resource_id,
                metadata_json, captured_at_ms
            ) VALUES
                ('resource-google', 'run-1', 'google_workspace', 'TASKS', 'TASK',
                 'shared-task-id', '{}', 1),
                ('resource-github', 'run-1', 'github', 'GITHUB', 'TASK',
                 'shared-task-id', '{}', 1);
            """
        )

        rows = connection.execute(
            """
            SELECT connector_id, source, resource_type, resource_id
            FROM resource_refs
            WHERE run_id = 'run-1' AND resource_id = 'shared-task-id'
            ORDER BY connector_id;
            """
        ).fetchall()
        assert [tuple(row) for row in rows] == [
            ("github", "GITHUB", "TASK", "shared-task-id"),
            ("google_workspace", "TASKS", "TASK", "shared-task-id"),
        ]
    finally:
        connection.close()


def _seed_populated_google_history(connection: sqlite3.Connection) -> None:
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
        ) VALUES ('run-1', 'conversation-1', 'AGENT_SEARCH', 'VERIFYING',
                  'thread-1', 'AUTO', '{}', 1, 1);
        """
    )
    connection.execute(
        """
        INSERT INTO plans (
            id, run_id, revision_no, status, summary_text, created_at_ms,
            review_status, review_version
        ) VALUES ('plan-1', 'run-1', 1, 'ACTIVE', NULL, 1, 'PASSED', 0);
        """
    )
    connection.execute(
        """
        INSERT INTO resource_refs (
            id, run_id, source, resource_type, resource_id, parent_resource_id,
            canonical_url, title, event_time_ms, version_token, metadata_json, captured_at_ms
        ) VALUES (
            'resource-google', 'run-1', 'TASKS', 'TASK', 'shared-task-id', NULL,
            NULL, 'Task', NULL, 'version-1', '{"status":"needsAction"}', 1
        );
        """
    )
    connection.execute(
        """
        INSERT INTO actions (
            id, plan_id, position, tool_name, effect_type, approval_requirement,
            verification_policy, recovery_policy, target_resource_ref_id, status,
            arguments_json, arguments_hash, expected_json, risk_json, version,
            created_at_ms, updated_at_ms
        ) VALUES (
            'action-1', 'plan-1', 1, 'tasks_update_task', 'UPDATE', 'REQUIRED',
            'GET_COMPARE', 'GET_TARGET', 'resource-google', 'EXECUTED', '{}', ?,
            '{}', '{}', 3, 1, 1
        );
        """,
        ("a" * 64,),
    )
    connection.execute(
        """
        INSERT INTO approvals (
            id, action_id, approval_no, action_version, status, approved_by_account_id,
            arguments_snapshot_json, canonical_arguments_hash, source_snapshot_json,
            source_snapshot_hash, policy_version, tool_schema_version, idempotency_key,
            recovery_fingerprint, approved_at_ms, expires_at_ms, consumed_at_ms
        ) VALUES (
            'approval-1', 'action-1', 1, 1, 'CONSUMED', 'account-1', '{}', ?, '{}', ?,
            'policy-1', 'schema-1', ?, ?, 1, 999, 2
        );
        """,
        ("b" * 64, "c" * 64, "d" * 64, "e" * 64),
    )
    connection.execute(
        """
        INSERT INTO execution_attempts (
            id, approval_id, attempt_no, status, version, result_resource_ref_id,
            response_metadata_json, started_at_ms, finished_at_ms
        ) VALUES (
            'attempt-1', 'approval-1', 1, 'SUCCEEDED', 1, 'resource-google', '{}', 2, 3
        );
        """
    )
    connection.execute(
        """
        INSERT INTO verifications (
            id, execution_attempt_id, verification_no, status, normalizer_version,
            expected_json, actual_json, diff_json, verified_at_ms
        ) VALUES (
            'verification-1', 'attempt-1', 1, 'VERIFIED', 'normalizer-1',
            '{}', '{}', '{}', 4
        );
        """
    )
    connection.execute(
        """
        INSERT INTO command_receipts (
            command_id, command_type, request_hash, aggregate_type, aggregate_id,
            status, result_code, result_version, response_json, created_at_ms, completed_at_ms
        ) VALUES (
            'command-1', 'StoreWriteActionSuccess', ?, 'Action', 'action-1',
            'APPLIED', 'TRANSITION_APPLIED', 3, '{}', 1, 2
        );
        """,
        ("f" * 64,),
    )
    connection.execute(
        """
        INSERT INTO audit_events (
            account_id, run_id, action_id, actor_type, actor_id,
            event_type, outcome, metadata_json, created_at_ms
        ) VALUES (
            NULL, 'run-1', 'action-1', 'SYSTEM', 'test', 'WRITE_EXECUTED', 'APPLIED', '{}', 1
        );
        """
    )
    connection.execute(
        """
        INSERT INTO trace_events (
            run_id, action_id, event_type, status, payload_json, created_at_ms
        ) VALUES ('run-1', 'action-1', 'WRITE_ACTION_EXECUTED', 'EXECUTED', '{}', 1);
        """
    )
    connection.commit()


def _history_counts(connection: sqlite3.Connection) -> dict[str, int]:
    tables = (
        "actions",
        "resource_refs",
        "approvals",
        "execution_attempts",
        "verifications",
        "command_receipts",
        "audit_events",
        "trace_events",
    )
    return {
        table: int(connection.execute(f"SELECT COUNT(*) FROM {table};").fetchone()[0])
        for table in tables
    }
