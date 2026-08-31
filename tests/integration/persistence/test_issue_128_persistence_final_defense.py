import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.migration import apply_migrations

MIGRATIONS_DIR = Path("src/google_work_agent/adapters/persistence/migrations")
MANIFEST_PATH = Path("src/google_work_agent/application/tool_registry/tool_registry_manifest.json")
HASH = "a" * 64


def _migrations_through_0015(tmp_path: Path) -> Path:
    target = tmp_path / "through-0015"
    target.mkdir()
    for source in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if source.name <= "0015_verification_final_defense.sql":
            shutil.copyfile(source, target / source.name)
    return target


def _seed_account_run(
    connection: sqlite3.Connection,
    suffix: str,
    *,
    account_id: str = "account-1",
) -> None:
    connection.execute(
        "INSERT OR IGNORE INTO google_accounts VALUES (?, ?, NULL, 1, NULL);",
        (account_id, f"{account_id}@example.com"),
    )
    connection.execute(
        "INSERT INTO conversations VALUES (?, ?, ?, 1, 1);",
        (f"conversation-{suffix}", account_id, f"Conversation {suffix}"),
    )
    connection.execute(
        """
        INSERT INTO runs (
            id, conversation_id, entry_mode, status, langgraph_thread_id,
            requested_mode, budget_json, version, started_at_ms
        ) VALUES (?, ?, 'AGENT_SEARCH', 'WAITING_APPROVAL', ?, 'AUTO', '{}', 0, 1);
        """,
        (f"run-{suffix}", f"conversation-{suffix}", f"thread-{suffix}"),
    )


def _insert_plan(
    connection: sqlite3.Connection,
    suffix: str,
    *,
    revision_no: int = 1,
    status: str = "WAITING_APPROVAL",
    review_status: str = "PASSED",
    review_disposition: str | None = "PASS",
) -> str:
    plan_id = f"plan-{suffix}-{revision_no}"
    connection.execute(
        """
        INSERT INTO plans (
            id, run_id, revision_no, status, summary_text, created_at_ms,
            review_status, review_version, review_disposition
        ) VALUES (?, ?, ?, ?, 'Plan', 1, ?, 1, ?);
        """,
        (
            plan_id,
            f"run-{suffix}",
            revision_no,
            status,
            review_status,
            review_disposition,
        ),
    )
    return plan_id


def _insert_action(
    connection: sqlite3.Connection,
    action_id: str,
    plan_id: str,
    *,
    position: int = 1,
    status: str = "APPROVED",
) -> None:
    connection.execute(
        """
        INSERT INTO actions (
            id, plan_id, connector_id, position, tool_name, effect_type,
            approval_requirement, verification_policy, recovery_policy, status,
            arguments_json, arguments_hash, expected_json, risk_json, version,
            created_at_ms, updated_at_ms
        ) VALUES (?, ?, 'google_workspace', ?, 'tasks_create_task', 'CREATE',
                  'REQUIRED', 'GET_COMPARE', 'RESOURCE_SEARCH', ?, '{}', ?, '{}',
                  '{}', 1, 1, 1);
        """,
        (action_id, plan_id, position, status, HASH),
    )


def _insert_approval(
    connection: sqlite3.Connection,
    approval_id: str,
    action_id: str,
    *,
    status: str = "ACTIVE",
) -> None:
    unique_hash = hashlib.sha256(approval_id.encode()).hexdigest()
    connection.execute(
        """
        INSERT INTO approvals (
            id, action_id, approval_no, action_version, status,
            approved_by_account_id, arguments_snapshot_json,
            canonical_arguments_hash, source_snapshot_json, source_snapshot_hash,
            policy_version, tool_schema_version, idempotency_key,
            recovery_fingerprint, approved_at_ms, expires_at_ms, consumed_at_ms
        ) VALUES (?, ?, 1, 1, ?, 'account-1', '{}', ?, '{}', ?, 'p1', 's1',
                  ?, ?, 1, 100, ?);
        """,
        (
            approval_id,
            action_id,
            status,
            HASH,
            "b" * 64,
            unique_hash,
            hashlib.sha256(f"recovery:{approval_id}".encode()).hexdigest(),
            2 if status == "CONSUMED" else None,
        ),
    )


def test_0016_populated_upgrade_normalizes_durable_identity_and_accounts(
    tmp_path: Path,
) -> None:
    predecessor = _migrations_through_0015(tmp_path)
    connection = connect_sqlite(tmp_path / "upgrade.db")
    try:
        apply_migrations(connection, migrations_dir=predecessor, now_ms=lambda: 1)
        connection.execute(
            "INSERT INTO google_accounts VALUES ('account-1', 'a@example.com', NULL, 1, NULL);"
        )
        connection.execute(
            "INSERT INTO google_accounts VALUES ('account-2', 'b@example.com', NULL, 2, NULL);"
        )
        _seed_account_run(connection, "upgrade", account_id="account-1")
        connection.execute(
            """
            INSERT INTO plans (
                id, run_id, revision_no, status, summary_text, created_at_ms,
                review_status, review_version, review_disposition
            ) VALUES ('plan-upgrade', 'run-upgrade', 1, 'DRAFT', 'Plan', 1,
                      'REVISE', 1, NULL);
            """
        )
        connection.execute(
            """
            INSERT INTO resource_refs (
                id, run_id, connector_id, source, resource_type, resource_id,
                metadata_json, captured_at_ms
            ) VALUES ('resource-upgrade', 'run-upgrade', 'google_workspace',
                      'TASKS', 'TASK', 'task-1', '{}', 1);
            """
        )
        connection.commit()

        results = apply_migrations(connection, now_ms=lambda: 2)

        assert [result.applied for result in results] == [False] * 15 + [True] * 3
        assert tuple(
            connection.execute(
                "SELECT review_status, review_disposition FROM plans WHERE id='plan-upgrade';"
            ).fetchone()
        ) == ("REQUIRED", "REVISE")
        assert tuple(
            connection.execute(
                "SELECT connector_id, resource_type FROM resource_refs WHERE id='resource-upgrade';"
            ).fetchone()
        ) == ("google_workspace", "task")
        assert "source" not in {
            row[1] for row in connection.execute("PRAGMA table_info(resource_refs);")
        }
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM google_accounts WHERE disconnected_at_ms IS NULL;"
            ).fetchone()[0]
            == 1
        )
        assert connection.execute("PRAGMA quick_check;").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check;").fetchall() == []
    finally:
        connection.close()


def test_registry_identity_exactly_matches_signed_manifest(tmp_path: Path) -> None:
    connection = connect_sqlite(tmp_path / "registry.db")
    try:
        apply_migrations(connection, now_ms=lambda: 1)
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        expected = {
            (entry["connector_id"], entry["resource_type"]) for entry in manifest["entries"]
        }
        actual = {
            tuple(row)
            for row in connection.execute(
                "SELECT connector_id, resource_type FROM registered_connector_resource_types;"
            )
        }
        assert actual == expected

        _seed_account_run(connection, "registry")
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY constraint failed"):
            connection.execute(
                """
                INSERT INTO resource_refs (
                    id, run_id, connector_id, resource_type, resource_id,
                    metadata_json, captured_at_ms
                ) VALUES ('bad-resource', 'run-registry', 'google_workspace',
                          'TASK', 'task-1', '{}', 1);
                """
            )
    finally:
        connection.close()


def test_result_resource_and_historical_lineage_are_db_defended(tmp_path: Path) -> None:
    connection = connect_sqlite(tmp_path / "lineage.db")
    try:
        apply_migrations(connection, now_ms=lambda: 1)
        _seed_account_run(connection, "one")
        plan_id = _insert_plan(connection, "one")
        _insert_action(connection, "action-one", plan_id)
        _insert_approval(connection, "approval-one", "action-one", status="CONSUMED")
        connection.execute("UPDATE actions SET status='EXECUTING' WHERE id='action-one';")
        connection.execute(
            """
            INSERT INTO execution_attempts (
                id, approval_id, attempt_no, status, started_at_ms
            ) VALUES ('attempt-one', 'approval-one', 1, 'CLAIMED', 2);
            """
        )
        connection.execute(
            """
            INSERT INTO resource_refs (
                id, run_id, connector_id, resource_type, resource_id,
                metadata_json, captured_at_ms
            ) VALUES ('resource-one', 'run-one', 'google_workspace', 'task',
                      'task-one', '{}', 2);
            """
        )
        _seed_account_run(connection, "two")
        connection.execute(
            """
            INSERT INTO resource_refs (
                id, run_id, connector_id, resource_type, resource_id,
                metadata_json, captured_at_ms
            ) VALUES ('resource-two', 'run-two', 'google_workspace', 'task',
                      'task-two', '{}', 2);
            """
        )

        with pytest.raises(sqlite3.IntegrityError, match="ISSUE128_ATTEMPT_RESULT_RESOURCE_RUN"):
            connection.execute(
                "UPDATE execution_attempts SET result_resource_ref_id='resource-two' "
                "WHERE id='attempt-one';"
            )
        connection.execute(
            "UPDATE execution_attempts SET result_resource_ref_id='resource-one' "
            "WHERE id='attempt-one';"
        )
        with pytest.raises(
            sqlite3.IntegrityError, match="ISSUE128_ATTEMPT_RESULT_RESOURCE_IMMUTABLE"
        ):
            connection.execute(
                "UPDATE execution_attempts SET result_resource_ref_id=NULL WHERE id='attempt-one';"
            )

        mutations = (
            ("UPDATE plans SET revision_no=2 WHERE id='plan-one-1';", "ISSUE128_PLAN_LINEAGE"),
            (
                "UPDATE actions SET plan_id='missing' WHERE id='action-one';",
                "ISSUE128_ACTION_LINEAGE",
            ),
            (
                "UPDATE approvals SET approval_no=2 WHERE id='approval-one';",
                "ISSUE128_APPROVAL_LINEAGE",
            ),
            (
                "UPDATE execution_attempts SET attempt_no=2 WHERE id='attempt-one';",
                "ISSUE128_ATTEMPT_LINEAGE",
            ),
            (
                "UPDATE resource_refs SET resource_id='other' WHERE id='resource-one';",
                "ISSUE128_RESOURCE_REF_IDENTITY",
            ),
        )
        for statement, error_code in mutations:
            with pytest.raises(sqlite3.IntegrityError, match=error_code):
                connection.execute(statement)
    finally:
        connection.close()


def test_current_plan_review_and_unknown_result_authority_are_db_defended(
    tmp_path: Path,
) -> None:
    connection = connect_sqlite(tmp_path / "authority.db")
    try:
        apply_migrations(connection, now_ms=lambda: 1)
        _seed_account_run(connection, "authority")
        plan_id = _insert_plan(connection, "authority")
        _insert_action(connection, "action-active", plan_id)
        _insert_approval(connection, "approval-active", "action-active")

        with pytest.raises(sqlite3.IntegrityError, match="NFR019_PLAN_ACTIVE_APPROVAL"):
            connection.execute(
                "UPDATE plans SET review_status='REQUIRED', "
                "review_disposition='REVISE' WHERE id=?;",
                (plan_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="NFR019_PLAN_ACTIVE_APPROVAL"):
            _insert_plan(connection, "authority", revision_no=2, status="DRAFT")

        connection.execute("UPDATE approvals SET status='REVOKED' WHERE id='approval-active';")
        connection.execute("UPDATE plans SET status='SUPERSEDED' WHERE id=?;", (plan_id,))
        current_plan_id = _insert_plan(
            connection,
            "authority",
            revision_no=2,
            status="DRAFT",
            review_status="REQUIRED",
            review_disposition=None,
        )
        with pytest.raises(
            sqlite3.IntegrityError, match="ISSUE128_ACTION_NOT_CURRENT_PLAN_AUTHORITY"
        ):
            connection.execute("UPDATE actions SET status='MODIFIED' WHERE id='action-active';")
        with pytest.raises(sqlite3.IntegrityError, match="ISSUE128_PLAN_REVIEW_SNAPSHOT"):
            connection.execute(
                "UPDATE plans SET review_status='PASSED', review_disposition='BLOCK' WHERE id=?;",
                (current_plan_id,),
            )

        _seed_account_run(connection, "unknown")
        unknown_plan = _insert_plan(connection, "unknown")
        _insert_action(connection, "action-unknown", unknown_plan)
        _insert_approval(connection, "approval-unknown", "action-unknown", status="CONSUMED")
        connection.execute("UPDATE actions SET status='EXECUTING' WHERE id='action-unknown';")
        connection.execute(
            """
            INSERT INTO execution_attempts (
                id, approval_id, attempt_no, status, started_at_ms
            ) VALUES ('attempt-unknown', 'approval-unknown', 1, 'CLAIMED', 2);
            """
        )
        connection.execute(
            "UPDATE execution_attempts SET status='UNKNOWN_RESULT' WHERE id='attempt-unknown';"
        )
        connection.execute("UPDATE actions SET status='UNKNOWN_RESULT' WHERE id='action-unknown';")
        _insert_action(
            connection,
            "action-sibling",
            unknown_plan,
            position=2,
            status="PROPOSED",
        )
        with pytest.raises(sqlite3.IntegrityError, match="ISSUE128_UNKNOWN_RESULT_AUTHORITY"):
            connection.execute("UPDATE actions SET status='APPROVED' WHERE id='action-sibling';")
    finally:
        connection.close()
