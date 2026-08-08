import shutil
from pathlib import Path

import pytest

from google_work_agent.adapters.persistence import (
    apply_migrations,
    calculate_migration_checksum,
    connect_sqlite,
    discover_migrations,
)
from google_work_agent.adapters.persistence.errors import (
    MigrationApplyError,
    MigrationChecksumMismatchError,
    MigrationDiscoveryError,
    MigrationIntegrityError,
)

OFFICIAL_NORMALIZED_CHECKSUM = "77386baca1badadd6a79860823250836f7a6464e7f01bd865c3a84af094aa928"


def test_lf_and_crlf_sql_have_same_official_checksum() -> None:
    lf_sql = Path("docs/0001_initial.sql").read_bytes().replace(b"\r\n", b"\n")
    crlf_sql = lf_sql.replace(b"\n", b"\r\n")

    assert calculate_migration_checksum(lf_sql) == calculate_migration_checksum(crlf_sql)
    assert calculate_migration_checksum(crlf_sql) == OFFICIAL_NORMALIZED_CHECKSUM


def test_checksum_changes_when_sql_content_changes() -> None:
    raw = Path("docs/0001_initial.sql").read_bytes()
    changed = raw.replace(b"Google Work Agent", b"Google Work Agenu", 1)

    assert calculate_migration_checksum(changed) != OFFICIAL_NORMALIZED_CHECKSUM


def test_docs_and_runtime_sql_raw_bytes_are_identical() -> None:
    docs_sql = Path("docs/0001_initial.sql").read_bytes()
    runtime_sql = Path(
        "src/google_work_agent/adapters/persistence/migrations/0001_initial.sql"
    ).read_bytes()

    assert runtime_sql == docs_sql


def test_docs_and_runtime_second_migration_sql_raw_bytes_are_identical() -> None:
    docs_sql = Path("docs/0002_action_effect_send_delete.sql").read_bytes()
    runtime_sql = Path(
        "src/google_work_agent/adapters/persistence/migrations/0002_action_effect_send_delete.sql"
    ).read_bytes()

    assert runtime_sql == docs_sql


def test_package_resource_discovers_initial_migration() -> None:
    migrations = discover_migrations()

    assert len(migrations) == 2
    assert migrations[0].version == 1
    assert migrations[0].name == "initial"
    assert migrations[0].checksum == OFFICIAL_NORMALIZED_CHECKSUM
    assert migrations[1].version == 2
    assert migrations[1].name == "action_effect_send_delete"


def test_apply_initial_migration_records_official_checksum_and_is_idempotent(
    tmp_path: Path,
) -> None:
    connection = connect_sqlite(tmp_path / "migration.db")
    try:
        first_results = apply_migrations(connection, now_ms=lambda: 123456789)
        rows = connection.execute(
            "SELECT version, name, checksum, applied_at_ms FROM schema_migrations ORDER BY version;"
        ).fetchall()

        assert len(first_results) == 2
        assert first_results[0].applied is True
        assert first_results[1].applied is True
        assert [(row["version"], row["name"]) for row in rows] == [
            (1, "initial"),
            (2, "action_effect_send_delete"),
        ]
        assert rows[0]["checksum"] == OFFICIAL_NORMALIZED_CHECKSUM
        assert rows[0]["applied_at_ms"] == 123456789
        assert rows[1]["applied_at_ms"] == 123456789

        second_results = apply_migrations(connection, now_ms=lambda: 987654321)
        rows = connection.execute(
            "SELECT version, name, checksum, applied_at_ms FROM schema_migrations ORDER BY version;"
        ).fetchall()

        assert len(second_results) == 2
        assert second_results[0].applied is False
        assert second_results[1].applied is False
        assert len(rows) == 2
        assert rows[0]["applied_at_ms"] == 123456789
        assert rows[1]["applied_at_ms"] == 123456789
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
    shutil.copyfile(Path("docs/0001_initial.sql"), migrations_dir / "0001_initial.sql")
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
