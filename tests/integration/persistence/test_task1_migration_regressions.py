import shutil
from pathlib import Path

from google_work_agent.adapters.persistence import (
    apply_migrations,
    calculate_migration_checksum,
    connect_sqlite,
)

RUNTIME_MIGRATIONS_DIR = Path("src/google_work_agent/adapters/persistence/migrations")
HISTORICAL_CHECKSUMS = {
    "0001_initial.sql": "77386baca1badadd6a79860823250836f7a6464e7f01bd865c3a84af094aa928",
    "0002_action_effect_send_delete.sql": (
        "0cbd43fbaa351b19540128f860c4e88e827b263329b102cbe9016c1190145624"
    ),
    "0003_action_cancelled.sql": "d56a55a7fd4f5cec5d34705bf1cb09c218d22b762956b38af79a983faa033403",
    "0004_plan_review_gate.sql": "d12a4fc67101c3d14ff0ec57175c9d19ba765fe0eab41e0d5b3875b48b388f95",
    "0005_cross_aggregate_invariants.sql": (
        "ff2508e23c238a1b7bb3ec604031f7598cceff2285378767b61651590f5b109b"
    ),
}


def test_historical_migration_checksums_remain_immutable() -> None:
    for filename, expected in HISTORICAL_CHECKSUMS.items():
        actual = calculate_migration_checksum((RUNTIME_MIGRATIONS_DIR / filename).read_bytes())
        assert actual == expected


def test_populated_v1_2_upgrade_preserves_action_children_and_approval(tmp_path: Path) -> None:
    v1_2_dir = tmp_path / "v1-2-migrations"
    v1_2_dir.mkdir()
    shutil.copyfile(
        RUNTIME_MIGRATIONS_DIR / "0001_initial.sql",
        v1_2_dir / "0001_initial.sql",
    )
    connection = connect_sqlite(tmp_path / "populated-v1-2.db")
    try:
        apply_migrations(connection, migrations_dir=v1_2_dir, now_ms=lambda: 1)
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
            ) VALUES ('run-1', 'conversation-1', 'AGENT_SEARCH', 'WAITING_APPROVAL',
                      'thread-1', 'AUTO', '{}', 0, 1);
            """
        )
        connection.execute(
            "INSERT INTO plans VALUES ('plan-1', 'run-1', 1, 'WAITING_APPROVAL', 'Plan', 1);"
        )
        connection.execute(
            """
            INSERT INTO resource_refs (
                id, run_id, source, resource_type, resource_id, metadata_json, captured_at_ms
            ) VALUES ('resource-1', 'run-1', 'TASKS', 'TASK', 'task-1', '{}', 1);
            """
        )
        for action_id, position, status, arguments_hash in (
            ("action-1", 1, "APPROVED", "a" * 64),
            ("action-2", 2, "PROPOSED", "b" * 64),
        ):
            connection.execute(
                """
                INSERT INTO actions (
                    id, plan_id, position, tool_name, effect_type, approval_requirement,
                    verification_policy, recovery_policy, target_resource_ref_id, status,
                    arguments_json, arguments_hash, expected_json, risk_json, version,
                    created_at_ms, updated_at_ms
                ) VALUES (?, 'plan-1', ?, 'tasks_create_task', 'CREATE', 'REQUIRED',
                          'GET_COMPARE', 'RESOURCE_SEARCH', NULL, ?, '{}', ?, '{}', '{}', 0, 1, 1);
                """,
                (action_id, position, status, arguments_hash),
            )
        connection.execute("INSERT INTO action_dependencies VALUES ('action-2', 'action-1');")
        connection.execute(
            """
            INSERT INTO evidence (
                id, run_id, origin_type, resource_ref_id, message_id, kind,
                excerpt, locator_json, created_at_ms
            ) VALUES ('evidence-1', 'run-1', 'GOOGLE_RESOURCE', 'resource-1', NULL,
                      'TASK', 'evidence', '{}', 1);
            """
        )
        connection.execute("INSERT INTO action_evidence VALUES ('action-1', 'evidence-1');")
        connection.execute(
            """
            INSERT INTO approvals (
                id, action_id, approval_no, action_version, status, approved_by_account_id,
                approved_by_display, arguments_snapshot_json, canonical_arguments_hash,
                source_snapshot_json, source_snapshot_hash, policy_version, tool_schema_version,
                idempotency_key, recovery_fingerprint, approved_at_ms, expires_at_ms,
                consumed_at_ms
            ) VALUES ('approval-1', 'action-1', 1, 0, 'ACTIVE', 'account-1', NULL, '{}', ?,
                      '{}', ?, 'p1', 's1', ?, ?, 1, 100, NULL);
            """,
            ("c" * 64, "d" * 64, "e" * 64, "f" * 64),
        )

        results = apply_migrations(connection, now_ms=lambda: 2)

        # 0001 is already applied (False); 0002-0010 apply in order.
        assert [result.applied for result in results] == [
            False,
            True,
            True,
            True,
            True,
            True,
            True,
            True,
            True,
            True,
            True,
            True,
        ]
        assert connection.execute("SELECT COUNT(*) FROM actions;").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM action_dependencies;").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM evidence;").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM action_evidence;").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM approvals;").fetchone()[0] == 1
        assert connection.execute("PRAGMA foreign_key_check;").fetchall() == []
    finally:
        connection.close()
