import shutil
import sqlite3
from pathlib import Path

import pytest

from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.migration import apply_migrations
from google_work_agent.adapters.persistence.persistence_exceptions import MigrationApplyError

RUNTIME_MIGRATIONS_DIR = Path("src/google_work_agent/adapters/persistence/migrations")


def _predecessor_migrations(tmp_path: Path) -> Path:
    target = tmp_path / "through-0014"
    target.mkdir()
    for source in sorted(RUNTIME_MIGRATIONS_DIR.glob("*.sql")):
        if source.name <= "0014_run_terminal_result_kind.sql":
            shutil.copyfile(source, target / source.name)
    return target


def _seed_parent_graph(
    connection: sqlite3.Connection,
    *,
    run_status: str = "WAITING_APPROVAL",
    plan_status: str = "WAITING_APPROVAL",
    effect_type: str = "CREATE",
) -> None:
    approval_requirement = "NONE" if effect_type == "READ" else "REQUIRED"
    verification_policy = "NONE" if effect_type == "READ" else "GET_COMPARE"
    recovery_policy = "NONE" if effect_type == "READ" else "RESOURCE_SEARCH"
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
        ) VALUES ('run-1', 'conversation-1', 'AGENT_SEARCH', ?,
                  'thread-1', 'AUTO', '{}', 0, 1);
        """,
        (run_status,),
    )
    connection.execute(
        """
        INSERT INTO plans (
            id, run_id, revision_no, status, summary_text, created_at_ms,
            review_status, review_version, review_disposition
        ) VALUES ('plan-1', 'run-1', 1, ?, 'Plan', 1, 'PASSED', 1, 'PASS');
        """,
        (plan_status,),
    )
    connection.execute(
        """
        INSERT INTO actions (
            id, plan_id, connector_id, position, tool_name, effect_type,
            approval_requirement, verification_policy, recovery_policy, status,
            arguments_json, arguments_hash, expected_json, risk_json, version,
            created_at_ms, updated_at_ms
        ) VALUES ('action-1', 'plan-1', 'google_workspace', 1, 'tasks_create_task', ?,
                  ?, ?, ?, 'APPROVED',
                  '{}', ?, '{}', '{}', 1, 1, 1);
        """,
        (
            effect_type,
            approval_requirement,
            verification_policy,
            recovery_policy,
            "a" * 64,
        ),
    )


def _insert_approval(
    connection: sqlite3.Connection,
    *,
    approval_id: str = "approval-1",
    status: str = "ACTIVE",
    action_version: int = 1,
) -> None:
    connection.execute(
        """
        INSERT INTO approvals (
            id, action_id, approval_no, action_version, status, approved_by_account_id,
            approved_by_display, arguments_snapshot_json, canonical_arguments_hash,
            source_snapshot_json, source_snapshot_hash, policy_version, tool_schema_version,
            idempotency_key, recovery_fingerprint, approved_at_ms, expires_at_ms,
            consumed_at_ms
        ) VALUES (?, 'action-1', 1, ?, ?, 'account-1', NULL, '{}', ?,
                  '{}', ?, 'p1', 's1', ?, ?, 1, 100, NULL);
        """,
        (approval_id, action_version, status, "b" * 64, "c" * 64, "d" * 64, "e" * 64),
    )


def _seed_succeeded_attempt(connection: sqlite3.Connection) -> None:
    _insert_approval(connection)
    connection.execute(
        "UPDATE approvals SET status='CONSUMED', consumed_at_ms=2 WHERE id='approval-1';"
    )
    connection.execute("UPDATE actions SET status='EXECUTING' WHERE id='action-1';")
    connection.execute(
        """
        INSERT INTO execution_attempts (
            id, approval_id, attempt_no, status, started_at_ms, finished_at_ms,
            response_metadata_json, error_detail_json
        ) VALUES ('attempt-1', 'approval-1', 1, 'CLAIMED', 2, NULL, NULL, NULL);
        """
    )
    connection.execute(
        "UPDATE execution_attempts SET status='SUCCEEDED', finished_at_ms=3 WHERE id='attempt-1';"
    )
    connection.execute("UPDATE actions SET status='EXECUTED' WHERE id='action-1';")


def _insert_verification(connection: sqlite3.Connection, status: str) -> None:
    connection.execute(
        """
        INSERT INTO verifications (
            id, execution_attempt_id, verification_no, status, normalizer_version,
            expected_json, actual_json, diff_json, verified_at_ms
        ) VALUES (?, 'attempt-1', 1, ?, 'v1', '{}', '{}', '{}', 4);
        """,
        (f"verification-{status.lower()}", status),
    )


@pytest.mark.parametrize("status", ["VERIFIED", "MISMATCH"])
def test_fresh_schema_accepts_only_canonical_verification_statuses(
    tmp_path: Path, status: str
) -> None:
    connection = connect_sqlite(tmp_path / f"verification-{status}.db")
    try:
        apply_migrations(connection, now_ms=lambda: 1)
        _seed_parent_graph(connection)
        _seed_succeeded_attempt(connection)
        _insert_verification(connection, status)
        assert connection.execute("SELECT status FROM verifications;").fetchone()[0] == status
        assert connection.execute("PRAGMA foreign_key_check;").fetchall() == []
    finally:
        connection.close()


@pytest.mark.parametrize("status", ["NOT_FOUND", "ERROR"])
def test_fresh_schema_rejects_technical_verification_observations(
    tmp_path: Path, status: str
) -> None:
    connection = connect_sqlite(tmp_path / f"verification-{status}.db")
    try:
        apply_migrations(connection, now_ms=lambda: 1)
        _seed_parent_graph(connection)
        _seed_succeeded_attempt(connection)
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
            _insert_verification(connection, status)
    finally:
        connection.close()


def test_populated_0014_upgrade_preserves_verification_and_all_defenses(
    tmp_path: Path,
) -> None:
    predecessor = _predecessor_migrations(tmp_path)
    connection = connect_sqlite(tmp_path / "populated-upgrade.db")
    try:
        apply_migrations(connection, migrations_dir=predecessor, now_ms=lambda: 1)
        _seed_parent_graph(connection)
        _seed_succeeded_attempt(connection)
        _insert_verification(connection, "VERIFIED")
        connection.commit()

        results = apply_migrations(connection, now_ms=lambda: 2)

        assert [result.applied for result in results] == [False] * 14 + [True] * 4
        assert tuple(connection.execute("SELECT id, status FROM verifications;").fetchone()) == (
            "verification-verified",
            "VERIFIED",
        )
        trigger_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger' AND "
                "(name LIKE 'trg_verifications_%' OR name='trg_actions_verification_guard_update');"
            )
        }
        assert trigger_names == {
            "trg_verifications_action_guard_insert",
            "trg_verifications_immutable_update",
            "trg_verifications_immutable_delete",
            "trg_actions_verification_guard_update",
        }
        with pytest.raises(sqlite3.IntegrityError, match="NFR019_VERIFICATION_IMMUTABLE"):
            connection.execute("UPDATE verifications SET normalizer_version='v2';")
        with pytest.raises(sqlite3.IntegrityError, match="NFR019_VERIFICATION_IMMUTABLE"):
            connection.execute("DELETE FROM verifications;")
        connection.execute("UPDATE actions SET status='VERIFIED' WHERE id='action-1';")
        assert connection.execute("PRAGMA foreign_key_check;").fetchall() == []
    finally:
        connection.close()


@pytest.mark.parametrize("legacy_status", ["NOT_FOUND", "ERROR"])
def test_0015_preflight_rejects_legacy_verification_without_partial_rebuild(
    tmp_path: Path, legacy_status: str
) -> None:
    predecessor = _predecessor_migrations(tmp_path)
    connection = connect_sqlite(tmp_path / f"blocked-{legacy_status}.db")
    try:
        apply_migrations(connection, migrations_dir=predecessor, now_ms=lambda: 1)
        _seed_parent_graph(connection)
        _seed_succeeded_attempt(connection)
        _insert_verification(connection, legacy_status)
        connection.commit()

        with pytest.raises(MigrationApplyError):
            apply_migrations(connection, now_ms=lambda: 2)

        assert (
            connection.execute("SELECT status FROM verifications;").fetchone()[0] == legacy_status
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM schema_migrations WHERE version=15;"
            ).fetchone()[0]
            == 0
        )
        assert connection.execute("PRAGMA foreign_keys;").fetchone()[0] == 1
        assert connection.execute("PRAGMA foreign_key_check;").fetchall() == []
    finally:
        connection.close()


@pytest.mark.parametrize("run_status", ["WAITING_APPROVAL", "VERIFYING"])
def test_active_approval_creation_accepts_exact_fresh_run_states(
    tmp_path: Path, run_status: str
) -> None:
    connection = connect_sqlite(tmp_path / f"approval-{run_status}.db")
    try:
        apply_migrations(connection, now_ms=lambda: 1)
        _seed_parent_graph(connection, run_status=run_status)
        _insert_approval(connection)
        assert connection.execute("SELECT status FROM approvals;").fetchone()[0] == "ACTIVE"
    finally:
        connection.close()


@pytest.mark.parametrize(
    "run_status",
    [
        "PLANNING",
        "WAITING_CONFIRMATION",
        "REAUTH_REQUIRED",
        "RECOVERY_REQUIRED",
        "CANCEL_REQUESTED",
        "FAILED",
        "BLOCKED",
    ],
)
def test_active_approval_creation_rejects_every_other_relevant_run_state(
    tmp_path: Path, run_status: str
) -> None:
    connection = connect_sqlite(tmp_path / f"approval-reject-{run_status}.db")
    try:
        apply_migrations(connection, now_ms=lambda: 1)
        _seed_parent_graph(connection, run_status=run_status)
        with pytest.raises(sqlite3.IntegrityError, match="NFR019_ACTIVE_APPROVAL_ACTION"):
            _insert_approval(connection)
    finally:
        connection.close()


@pytest.mark.parametrize(
    "run_status",
    [
        "WAITING_APPROVAL",
        "VERIFYING",
        "WAITING_CONFIRMATION",
        "REAUTH_REQUIRED",
        "RECOVERY_REQUIRED",
        "CANCEL_REQUESTED",
    ],
)
def test_existing_active_approval_may_remain_in_exact_suspension_states(
    tmp_path: Path, run_status: str
) -> None:
    connection = connect_sqlite(tmp_path / f"approval-remain-{run_status}.db")
    try:
        apply_migrations(connection, now_ms=lambda: 1)
        _seed_parent_graph(connection)
        _insert_approval(connection)
        connection.execute("UPDATE runs SET status=? WHERE id='run-1';", (run_status,))
        assert connection.execute("SELECT status FROM approvals;").fetchone()[0] == "ACTIVE"
    finally:
        connection.close()


@pytest.mark.parametrize(
    "run_status",
    ["CREATED", "ANALYZING", "RETRIEVING", "PLANNING", "EXECUTING", "FAILED", "BLOCKED"],
)
def test_existing_active_approval_cannot_survive_invalid_run_state(
    tmp_path: Path, run_status: str
) -> None:
    connection = connect_sqlite(tmp_path / f"approval-invalid-remain-{run_status}.db")
    try:
        apply_migrations(connection, now_ms=lambda: 1)
        _seed_parent_graph(connection)
        _insert_approval(connection)
        with pytest.raises(sqlite3.IntegrityError, match="NFR019_RUN_ACTIVE_APPROVAL"):
            connection.execute("UPDATE runs SET status=? WHERE id='run-1';", (run_status,))
    finally:
        connection.close()


def test_active_approval_plan_action_and_unique_final_defenses(tmp_path: Path) -> None:
    connection = connect_sqlite(tmp_path / "approval-defenses.db")
    try:
        apply_migrations(connection, now_ms=lambda: 1)
        _seed_parent_graph(connection)
        _insert_approval(connection)

        with pytest.raises(sqlite3.IntegrityError, match="NFR019_PLAN_ACTIVE_APPROVAL"):
            connection.execute("UPDATE plans SET status='ACTIVE' WHERE id='plan-1';")
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
            _insert_approval(connection, approval_id="approval-2")

        connection.execute("UPDATE approvals SET status='REVOKED' WHERE id='approval-1';")
        connection.execute("UPDATE plans SET status='ACTIVE' WHERE id='plan-1';")
        with pytest.raises(sqlite3.IntegrityError, match="NFR019_ACTIVE_APPROVAL_ACTION"):
            connection.execute("UPDATE approvals SET status='ACTIVE' WHERE id='approval-1';")
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("plan_status", "effect_type", "action_version"),
    [
        ("ACTIVE", "CREATE", 1),
        ("WAITING_APPROVAL", "READ", 1),
        ("WAITING_APPROVAL", "CREATE", 0),
    ],
)
def test_active_approval_rejects_invalid_plan_read_and_stale_version(
    tmp_path: Path, plan_status: str, effect_type: str, action_version: int
) -> None:
    connection = connect_sqlite(tmp_path / f"approval-{plan_status}-{effect_type}.db")
    try:
        apply_migrations(connection, now_ms=lambda: 1)
        _seed_parent_graph(connection, plan_status=plan_status, effect_type=effect_type)
        with pytest.raises(sqlite3.IntegrityError, match="NFR019_ACTIVE_APPROVAL_ACTION"):
            _insert_approval(connection, action_version=action_version)
    finally:
        connection.close()


def test_0015_preflight_rejects_existing_active_approval_on_legacy_active_plan(
    tmp_path: Path,
) -> None:
    predecessor = _predecessor_migrations(tmp_path)
    connection = connect_sqlite(tmp_path / "blocked-active-plan.db")
    try:
        apply_migrations(connection, migrations_dir=predecessor, now_ms=lambda: 1)
        _seed_parent_graph(connection, plan_status="ACTIVE")
        _insert_approval(connection)
        connection.commit()

        with pytest.raises(MigrationApplyError):
            apply_migrations(connection, now_ms=lambda: 2)

        assert connection.execute("SELECT status FROM approvals;").fetchone()[0] == "ACTIVE"
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM schema_migrations WHERE version=15;"
            ).fetchone()[0]
            == 0
        )
    finally:
        connection.close()
