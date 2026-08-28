import shutil
from pathlib import Path

import pytest

from google_work_agent.adapters.persistence import (
    apply_migrations,
    calculate_migration_checksum,
    connect_sqlite,
    discover_migrations,
)
from google_work_agent.adapters.persistence.persistence_exceptions import (
    MigrationApplyError,
    MigrationChecksumMismatchError,
    MigrationDiscoveryError,
    MigrationIntegrityError,
)

OFFICIAL_NORMALIZED_CHECKSUM = "77386baca1badadd6a79860823250836f7a6464e7f01bd865c3a84af094aa928"
OFFICIAL_V2_NORMALIZED_CHECKSUM = "0cbd43fbaa351b19540128f860c4e88e827b263329b102cbe9016c1190145624"
RUNTIME_MIGRATIONS_DIR = Path("src/google_work_agent/adapters/persistence/migrations")
DOCUMENTATION_MIGRATIONS_DIR = Path("docs/database/migrations")


def _normalized_sql(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n").rstrip(b"\n") + b"\n"


def test_lf_and_crlf_sql_have_same_official_checksum() -> None:
    lf_sql = (RUNTIME_MIGRATIONS_DIR / "0001_initial.sql").read_bytes().replace(b"\r\n", b"\n")
    crlf_sql = lf_sql.replace(b"\n", b"\r\n")

    assert calculate_migration_checksum(lf_sql) == calculate_migration_checksum(crlf_sql)
    assert calculate_migration_checksum(crlf_sql) == OFFICIAL_NORMALIZED_CHECKSUM


def test_v2_lf_and_crlf_have_same_official_checksum() -> None:
    lf_sql = (RUNTIME_MIGRATIONS_DIR / "0002_action_effect_send_delete.sql").read_bytes()
    lf_sql = lf_sql.replace(b"\r\n", b"\n")
    crlf_sql = lf_sql.replace(b"\n", b"\r\n")

    assert calculate_migration_checksum(lf_sql) == OFFICIAL_V2_NORMALIZED_CHECKSUM
    assert calculate_migration_checksum(crlf_sql) == OFFICIAL_V2_NORMALIZED_CHECKSUM


def test_checksum_changes_when_sql_content_changes() -> None:
    raw = (RUNTIME_MIGRATIONS_DIR / "0001_initial.sql").read_bytes()
    changed = raw.replace(b"Google Work Agent", b"Google Work Agenu", 1)

    assert calculate_migration_checksum(changed) != OFFICIAL_NORMALIZED_CHECKSUM


def test_documentation_mirror_matches_runtime_initial_migration() -> None:
    runtime_sql = _normalized_sql(RUNTIME_MIGRATIONS_DIR / "0001_initial.sql")
    documentation_mirror = _normalized_sql(DOCUMENTATION_MIGRATIONS_DIR / "0001_initial.sql")

    assert documentation_mirror == runtime_sql


def test_documentation_mirror_matches_runtime_second_migration() -> None:
    runtime_sql = _normalized_sql(RUNTIME_MIGRATIONS_DIR / "0002_action_effect_send_delete.sql")
    documentation_mirror = _normalized_sql(
        DOCUMENTATION_MIGRATIONS_DIR / "0002_action_effect_send_delete.sql"
    )

    assert documentation_mirror == runtime_sql


def test_documentation_mirror_matches_runtime_third_migration() -> None:
    runtime_sql = _normalized_sql(RUNTIME_MIGRATIONS_DIR / "0003_action_cancelled.sql")
    documentation_mirror = _normalized_sql(
        DOCUMENTATION_MIGRATIONS_DIR / "0003_action_cancelled.sql"
    )

    assert documentation_mirror == runtime_sql


def test_documentation_mirror_matches_runtime_fourth_migration() -> None:
    runtime_sql = _normalized_sql(RUNTIME_MIGRATIONS_DIR / "0004_plan_review_gate.sql")
    documentation_mirror = _normalized_sql(
        DOCUMENTATION_MIGRATIONS_DIR / "0004_plan_review_gate.sql"
    )

    assert documentation_mirror == runtime_sql


def test_documentation_mirror_matches_runtime_fifth_migration() -> None:
    runtime_sql = _normalized_sql(RUNTIME_MIGRATIONS_DIR / "0005_cross_aggregate_invariants.sql")
    documentation_mirror = _normalized_sql(
        DOCUMENTATION_MIGRATIONS_DIR / "0005_cross_aggregate_invariants.sql"
    )

    assert documentation_mirror == runtime_sql


def test_documentation_mirror_matches_runtime_sixth_migration() -> None:
    runtime_sql = _normalized_sql(RUNTIME_MIGRATIONS_DIR / "0006_plan_aggregate_invariants.sql")
    documentation_mirror = _normalized_sql(
        DOCUMENTATION_MIGRATIONS_DIR / "0006_plan_aggregate_invariants.sql"
    )

    assert documentation_mirror == runtime_sql


def test_documentation_mirror_matches_runtime_seventh_migration() -> None:
    runtime_sql = _normalized_sql(RUNTIME_MIGRATIONS_DIR / "0007_connector_neutral_persistence.sql")
    documentation_mirror = _normalized_sql(
        DOCUMENTATION_MIGRATIONS_DIR / "0007_connector_neutral_persistence.sql"
    )

    assert documentation_mirror == runtime_sql


def test_documentation_mirror_matches_runtime_eighth_migration() -> None:
    runtime_sql = _normalized_sql(
        RUNTIME_MIGRATIONS_DIR / "0008_resource_ref_connector_identity.sql"
    )
    documentation_mirror = _normalized_sql(
        DOCUMENTATION_MIGRATIONS_DIR / "0008_resource_ref_connector_identity.sql"
    )

    assert documentation_mirror == runtime_sql


def test_package_resource_discovers_initial_migration() -> None:
    migrations = discover_migrations()

    assert len(migrations) == 14
    assert migrations[0].version == 1
    assert migrations[0].name == "initial"
    assert migrations[0].checksum == OFFICIAL_NORMALIZED_CHECKSUM
    assert migrations[1].version == 2
    assert migrations[1].name == "action_effect_send_delete"
    assert migrations[2].version == 3
    assert migrations[2].name == "action_cancelled"
    assert migrations[3].version == 4
    assert migrations[3].name == "plan_review_gate"
    assert migrations[4].version == 5
    assert migrations[4].name == "cross_aggregate_invariants"
    assert migrations[5].version == 6
    assert migrations[5].name == "plan_aggregate_invariants"
    assert migrations[6].version == 7
    assert migrations[6].name == "connector_neutral_persistence"
    assert migrations[7].version == 8
    assert migrations[7].name == "resource_ref_connector_identity"
    assert migrations[8].version == 9
    assert migrations[8].name == "workflow_handoff_outbox"
    assert migrations[9].version == 10
    assert migrations[9].name == "plan_review_disposition"
    assert migrations[10].version == 11
    assert migrations[10].name == "recovery_context"
    assert migrations[11].version == 12
    assert migrations[11].name == "recovery_context_currentness"
    assert migrations[12].version == 13
    assert migrations[12].name == "resource_ref_registry_type"
    assert migrations[13].version == 14
    assert migrations[13].name == "run_terminal_result_kind"


def test_apply_initial_migration_records_official_checksum_and_is_idempotent(
    tmp_path: Path,
) -> None:
    connection = connect_sqlite(tmp_path / "migration.db")
    try:
        first_results = apply_migrations(connection, now_ms=lambda: 123456789)
        rows = connection.execute(
            "SELECT version, name, checksum, applied_at_ms FROM schema_migrations ORDER BY version;"
        ).fetchall()

        assert len(first_results) == 14
        assert all(result.applied for result in first_results)
        assert [(row["version"], row["name"]) for row in rows] == [
            (1, "initial"),
            (2, "action_effect_send_delete"),
            (3, "action_cancelled"),
            (4, "plan_review_gate"),
            (5, "cross_aggregate_invariants"),
            (6, "plan_aggregate_invariants"),
            (7, "connector_neutral_persistence"),
            (8, "resource_ref_connector_identity"),
            (9, "workflow_handoff_outbox"),
            (10, "plan_review_disposition"),
            (11, "recovery_context"),
            (12, "recovery_context_currentness"),
            (13, "resource_ref_registry_type"),
            (14, "run_terminal_result_kind"),
        ]
        assert rows[0]["checksum"] == OFFICIAL_NORMALIZED_CHECKSUM
        assert rows[1]["checksum"] == OFFICIAL_V2_NORMALIZED_CHECKSUM
        assert all(row["applied_at_ms"] == 123456789 for row in rows)

        second_results = apply_migrations(connection, now_ms=lambda: 987654321)
        rows = connection.execute(
            "SELECT version, name, checksum, applied_at_ms FROM schema_migrations ORDER BY version;"
        ).fetchall()

        assert len(second_results) == 14
        assert all(not result.applied for result in second_results)
        assert len(rows) == 14
        assert all(row["applied_at_ms"] == 123456789 for row in rows)
    finally:
        connection.close()


def test_crlf_applied_database_is_compatible_with_lf_runtime_migrations(
    tmp_path: Path,
) -> None:
    crlf_dir = tmp_path / "crlf-migrations"
    crlf_dir.mkdir()
    for source in sorted(RUNTIME_MIGRATIONS_DIR.glob("*.sql")):
        lf_bytes = source.read_bytes().replace(b"\r\n", b"\n")
        (crlf_dir / source.name).write_bytes(lf_bytes.replace(b"\n", b"\r\n"))

    connection = connect_sqlite(tmp_path / "windows-checkout.db")
    try:
        first_results = apply_migrations(
            connection,
            migrations_dir=crlf_dir,
            now_ms=lambda: 1,
        )
        second_results = apply_migrations(
            connection,
            migrations_dir=RUNTIME_MIGRATIONS_DIR,
            now_ms=lambda: 2,
        )
        rows = connection.execute(
            "SELECT version, checksum FROM schema_migrations ORDER BY version;"
        ).fetchall()

        assert all(result.applied for result in first_results)
        assert all(not result.applied for result in second_results)
        assert rows[1]["checksum"] == OFFICIAL_V2_NORMALIZED_CHECKSUM
        assert connection.execute("PRAGMA foreign_key_check;").fetchall() == []
    finally:
        connection.close()


def test_populated_0011_upgrade_preserves_current_recovery_context(tmp_path: Path) -> None:
    legacy_dir = tmp_path / "through-0011"
    legacy_dir.mkdir()
    for source in sorted(RUNTIME_MIGRATIONS_DIR.glob("*.sql")):
        if source.name <= "0011_recovery_context.sql":
            shutil.copyfile(source, legacy_dir / source.name)

    connection = connect_sqlite(tmp_path / "recovery-upgrade.db")
    try:
        apply_migrations(connection, migrations_dir=legacy_dir, now_ms=lambda: 1)
        connection.execute(
            "INSERT INTO google_accounts VALUES ('a-1', 'u@example.com', NULL, 1, NULL);"
        )
        connection.execute("INSERT INTO conversations VALUES ('c-1', 'a-1', 'Test', 1, 1);")
        connection.execute(
            """
            INSERT INTO runs (
                id, conversation_id, entry_mode, status, langgraph_thread_id,
                requested_mode, actual_runtime, budget_json, version, started_at_ms, finished_at_ms
            ) VALUES ('r-1', 'c-1', 'AGENT_SEARCH', 'RECOVERY_REQUIRED', 't-1',
                      'AUTO', NULL, '{}', 0, 1, NULL);
            """
        )
        connection.execute(
            """
            INSERT INTO recovery_contexts (
                run_id, reason, scope, action_id, pre_recovery_status,
                recovery_fingerprint, version, created_at_ms, updated_at_ms
            ) VALUES ('r-1', 'CHECKPOINT_MISMATCH', 'RUN', NULL, 'ANALYZING',
                      'fp-1', 0, 1, 1);
            """
        )
        connection.commit()

        results = apply_migrations(connection, now_ms=lambda: 2)

        assert [result.applied for result in results] == [False] * 11 + [True, True, True]
        row = connection.execute(
            "SELECT recovery_fingerprint, version FROM recovery_contexts WHERE run_id = 'r-1';"
        ).fetchone()
        assert row is not None
        assert tuple(row) == ("fp-1", 0)
        tombstone_count = connection.execute(
            "SELECT COUNT(*) FROM recovery_context_tombstones;"
        ).fetchone()[0]
        assert tombstone_count == 0
    finally:
        connection.close()


def test_populated_0013_upgrade_backfills_terminal_result_kind(tmp_path: Path) -> None:
    predecessor_dir = tmp_path / "through-0013"
    predecessor_dir.mkdir()
    for source in sorted(RUNTIME_MIGRATIONS_DIR.glob("*.sql")):
        if source.name <= "0013_resource_ref_registry_type.sql":
            shutil.copyfile(source, predecessor_dir / source.name)

    connection = connect_sqlite(tmp_path / "terminal-result-upgrade.db")
    try:
        apply_migrations(connection, migrations_dir=predecessor_dir, now_ms=lambda: 1)
        connection.execute(
            "INSERT INTO google_accounts VALUES ('a-1', 'u@example.com', NULL, 1, NULL);"
        )
        connection.execute("INSERT INTO conversations VALUES ('c-1', 'a-1', 'Test', 1, 1);")
        for suffix in ("success", "partial"):
            connection.execute(
                """
                INSERT INTO runs (
                    id, conversation_id, entry_mode, status, langgraph_thread_id,
                    requested_mode, budget_json, version, started_at_ms, finished_at_ms
                ) VALUES (?, 'c-1', 'AGENT_SEARCH', 'WAITING_APPROVAL', ?,
                          'AUTO', '{}', 0, 1, NULL);
                """,
                (f"run-{suffix}", f"thread-{suffix}"),
            )
            connection.execute(
                """
                INSERT INTO plans (id, run_id, revision_no, status, summary_text, created_at_ms)
                VALUES (?, ?, 1, 'WAITING_APPROVAL', 'Plan', 1);
                """,
                (f"plan-{suffix}", f"run-{suffix}"),
            )
            if suffix == "partial":
                connection.execute(
                    """
                    INSERT INTO actions (
                        id, plan_id, connector_id, position, tool_name, effect_type,
                        approval_requirement, verification_policy, recovery_policy, status,
                        arguments_json, arguments_hash, expected_json, created_at_ms, updated_at_ms
                    ) VALUES (?, ?, 'google_workspace', 1, 'tasks_create_task', 'CREATE',
                              'REQUIRED', 'GET_COMPARE', 'RESOURCE_SEARCH', 'PROPOSED',
                              '{}', ?, '{}', 1, 1);
                    """,
                    (f"action-{suffix}", f"plan-{suffix}", suffix[0] * 64),
                )
                connection.execute(
                    "UPDATE actions SET status = 'REJECTED' WHERE id = ?;",
                    (f"action-{suffix}",),
                )
            connection.execute(
                "UPDATE plans SET status = 'COMPLETED' WHERE id = ?;",
                (f"plan-{suffix}",),
            )
            connection.execute(
                "UPDATE runs SET status = 'COMPLETED', finished_at_ms = 2 WHERE id = ?;",
                (f"run-{suffix}",),
            )
        connection.commit()

        results = apply_migrations(connection, now_ms=lambda: 2)

        assert [result.applied for result in results] == [False] * 13 + [True]
        rows = connection.execute(
            "SELECT id, terminal_result_kind FROM runs ORDER BY id;"
        ).fetchall()
        assert [tuple(row) for row in rows] == [
            ("run-partial", "PARTIAL"),
            ("run-success", "SUCCESS"),
        ]
        assert connection.execute("PRAGMA foreign_key_check;").fetchall() == []
    finally:
        connection.close()


def test_v1_3_to_v1_4_preserves_rows_effect_contracts_and_foreign_keys(
    tmp_path: Path,
) -> None:
    v1_3_dir = tmp_path / "v1-3-migrations"
    v1_3_dir.mkdir()
    shutil.copyfile(
        RUNTIME_MIGRATIONS_DIR / "0001_initial.sql",
        v1_3_dir / "0001_initial.sql",
    )
    shutil.copyfile(
        RUNTIME_MIGRATIONS_DIR / "0002_action_effect_send_delete.sql",
        v1_3_dir / "0002_action_effect_send_delete.sql",
    )
    connection = connect_sqlite(tmp_path / "upgrade.db")
    try:
        apply_migrations(connection, migrations_dir=v1_3_dir, now_ms=lambda: 1)
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
        connection.execute("INSERT INTO plans VALUES ('plan-1', 'run-1', 1, 'ACTIVE', NULL, 1);")
        for position, effect, verification, recovery in (
            (1, "SEND", "SENT_LOOKUP", "MESSAGE_SEARCH"),
            (2, "DELETE", "GET_ABSENT", "GET_TARGET"),
        ):
            connection.execute(
                """
                INSERT INTO actions (
                    id, plan_id, position, tool_name, effect_type, approval_requirement,
                    verification_policy, recovery_policy, status, arguments_json,
                    arguments_hash, expected_json, version, created_at_ms, updated_at_ms
                ) VALUES (?, 'plan-1', ?, ?, ?, 'REQUIRED', ?, ?, 'PROPOSED',
                          '{}', ?, '{}', 0, 1, 1);
                """,
                (
                    f"action-{effect.lower()}",
                    position,
                    f"test_{effect.lower()}",
                    effect,
                    verification,
                    recovery,
                    str(position) * 64,
                ),
            )
        connection.commit()

        results = apply_migrations(connection, now_ms=lambda: 2)
        connection.execute("UPDATE actions SET status = 'CANCELLED' WHERE id = 'action-send';")

        assert [result.applied for result in results] == [
            False,
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
            True,
        ]
        rows = connection.execute(
            """
            SELECT id, effect_type, verification_policy, recovery_policy, status
            FROM actions ORDER BY position;
            """
        ).fetchall()
        assert [tuple(row) for row in rows] == [
            ("action-send", "SEND", "SENT_LOOKUP", "MESSAGE_SEARCH", "CANCELLED"),
            ("action-delete", "DELETE", "GET_ABSENT", "GET_TARGET", "PROPOSED"),
        ]
        assert connection.execute("PRAGMA foreign_key_check;").fetchall() == []
        indexes = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'actions';"
            )
        }
        assert {"ix_actions_plan_status", "ix_actions_recovery"} <= indexes
    finally:
        connection.close()


def test_cross_aggregate_upgrade_rejects_existing_impossible_snapshot(
    tmp_path: Path,
) -> None:
    upgrade_dir = tmp_path / "upgrade-migrations"
    upgrade_dir.mkdir()
    for version in range(1, 5):
        source = next(RUNTIME_MIGRATIONS_DIR.glob(f"{version:04d}_*.sql"))
        shutil.copyfile(source, upgrade_dir / source.name)

    connection = connect_sqlite(tmp_path / "invalid-upgrade.db")
    try:
        apply_migrations(connection, migrations_dir=upgrade_dir, now_ms=lambda: 1)
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
                requested_mode, budget_json, version, started_at_ms, finished_at_ms
            ) VALUES ('run-1', 'conversation-1', 'AGENT_SEARCH', 'COMPLETED',
                      'thread-1', 'AUTO', '{}', 1, 1, 2);
            """
        )
        connection.execute(
            """
            INSERT INTO plans (
                id, run_id, revision_no, status, created_at_ms, review_status, review_version
            ) VALUES ('plan-1', 'run-1', 1, 'ACTIVE', 1, 'PASSED', 0);
            """
        )
        connection.execute(
            """
            INSERT INTO actions (
                id, plan_id, position, tool_name, effect_type, approval_requirement,
                verification_policy, recovery_policy, status, arguments_json,
                arguments_hash, expected_json, version, created_at_ms, updated_at_ms
            ) VALUES ('action-1', 'plan-1', 1, 'gmail_get_thread', 'READ', 'NONE',
                      'NONE', 'NONE', 'PROPOSED', '{}', ?, '{}', 0, 1, 1);
            """,
            ("a" * 64,),
        )
        connection.commit()

        source = RUNTIME_MIGRATIONS_DIR / "0005_cross_aggregate_invariants.sql"
        shutil.copyfile(source, upgrade_dir / source.name)
        with pytest.raises(MigrationApplyError):
            apply_migrations(connection, migrations_dir=upgrade_dir, now_ms=lambda: 2)

        assert (
            connection.execute(
                "SELECT COUNT(*) FROM schema_migrations WHERE version = 5;"
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'trigger' AND name LIKE 'trg_%';"
            ).fetchone()[0]
            == 0
        )
    finally:
        connection.close()


def test_checksum_mismatch_is_blocked(tmp_path: Path) -> None:
    connection = connect_sqlite(tmp_path / "checksum-mismatch.db")
    try:
        apply_migrations(connection, now_ms=lambda: 1)
        connection.execute(
            "UPDATE schema_migrations SET checksum = ? WHERE version = 1;",
            ("0" * 64,),
        )

        with pytest.raises(MigrationChecksumMismatchError):
            apply_migrations(connection, now_ms=lambda: 2)
    finally:
        connection.close()


def test_name_mismatch_is_blocked(tmp_path: Path) -> None:
    connection = connect_sqlite(tmp_path / "name-mismatch.db")
    try:
        apply_migrations(connection, now_ms=lambda: 1)
        connection.execute("UPDATE schema_migrations SET name = ? WHERE version = 1;", ("renamed",))

        with pytest.raises(MigrationIntegrityError):
            apply_migrations(connection, now_ms=lambda: 2)
    finally:
        connection.close()


def test_invalid_filename_duplicate_version_and_empty_migration_are_blocked(
    tmp_path: Path,
) -> None:
    invalid_dir = tmp_path / "invalid"
    invalid_dir.mkdir()
    (invalid_dir / "initial.sql").write_text("SELECT 1;\n", encoding="utf-8")

    with pytest.raises(MigrationDiscoveryError):
        discover_migrations(invalid_dir)

    duplicate_dir = tmp_path / "duplicate"
    duplicate_dir.mkdir()
    (duplicate_dir / "0001_initial.sql").write_text("SELECT 1;\n", encoding="utf-8")
    (duplicate_dir / "0001_second.sql").write_text("SELECT 2;\n", encoding="utf-8")

    with pytest.raises(MigrationDiscoveryError):
        discover_migrations(duplicate_dir)

    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    (empty_dir / "0001_empty.sql").write_text("   \n", encoding="utf-8")

    with pytest.raises(MigrationDiscoveryError):
        discover_migrations(empty_dir)


def test_failed_migration_rolls_back_without_receipt_or_partial_table(tmp_path: Path) -> None:
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "0001_broken.sql").write_text(
        """
        CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            checksum TEXT NOT NULL CHECK (length(checksum) = 64),
            applied_at_ms INTEGER NOT NULL CHECK (applied_at_ms >= 0)
        );
        CREATE TABLE partial_table (id INTEGER PRIMARY KEY);
        INSERT INTO missing_table (id) VALUES (1);
        """,
        encoding="utf-8",
    )
    connection = connect_sqlite(tmp_path / "rollback.db")
    try:
        with pytest.raises(MigrationApplyError):
            apply_migrations(connection, migrations_dir=migrations_dir, now_ms=lambda: 1)

        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'partial_table';"
            ).fetchone()
            is None
        )
        assert (
            connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name = 'schema_migrations';
                """
            ).fetchone()
            is None
        )
        assert connection.execute("SELECT 1;").fetchone()[0] == 1
    finally:
        connection.close()


def test_second_migration_failure_preserves_first_migration(tmp_path: Path) -> None:
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    shutil.copyfile(
        RUNTIME_MIGRATIONS_DIR / "0001_initial.sql",
        migrations_dir / "0001_initial.sql",
    )
    (migrations_dir / "0002_broken.sql").write_text(
        """
        CREATE TABLE second_partial (id INTEGER PRIMARY KEY);
        INSERT INTO missing_table (id) VALUES (1);
        """,
        encoding="utf-8",
    )
    connection = connect_sqlite(tmp_path / "rollback-second.db")
    try:
        with pytest.raises(MigrationApplyError):
            apply_migrations(connection, migrations_dir=migrations_dir, now_ms=lambda: 1)

        rows = connection.execute(
            "SELECT version, name FROM schema_migrations ORDER BY version;"
        ).fetchall()
        assert [(row["version"], row["name"]) for row in rows] == [(1, "initial")]
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'second_partial';"
            ).fetchone()
            is None
        )
    finally:
        connection.close()
