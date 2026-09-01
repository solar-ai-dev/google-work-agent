"""Fresh-install schema baseline and migration-runner integrity tests."""

from __future__ import annotations

from pathlib import Path
from shutil import copyfile

import pytest

from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.migration import (
    apply_migrations,
    calculate_migration_checksum,
    discover_migrations,
)
from google_work_agent.adapters.persistence.persistence_exceptions import (
    MigrationApplyError,
    MigrationChecksumMismatchError,
    MigrationDiscoveryError,
    MigrationIntegrityError,
)

ROOT = Path(__file__).resolve().parents[3]
RUNTIME_MIGRATION = (
    ROOT / "src/google_work_agent/adapters/persistence/migrations/0001_current_schema.sql"
)
DOCUMENTATION_MIGRATION = ROOT / "docs/database/migrations/0001_current_schema.sql"

CURRENT_TABLES = {
    "action_dependencies",
    "action_evidence",
    "actions",
    "approvals",
    "audit_events",
    "command_receipts",
    "conversations",
    "evidence",
    "execution_attempts",
    "google_accounts",
    "messages",
    "plans",
    "recovery_context_tombstones",
    "recovery_contexts",
    "registered_connector_resource_types",
    "registered_connectors",
    "resource_refs",
    "runs",
    "schema_migrations",
    "trace_events",
    "verifications",
    "workflow_bindings",
    "workflow_handoffs",
}


def test_runtime_and_documentation_expose_one_identical_current_schema() -> None:
    runtime = RUNTIME_MIGRATION.read_bytes().replace(b"\r\n", b"\n")
    documented = DOCUMENTATION_MIGRATION.read_bytes().replace(b"\r\n", b"\n")

    assert documented == runtime
    migrations = discover_migrations()
    assert [(item.version, item.name) for item in migrations] == [(1, "current_schema")]
    assert migrations[0].checksum == calculate_migration_checksum(runtime)


def test_fresh_database_has_exact_current_tables_and_safety_objects(tmp_path: Path) -> None:
    connection = connect_sqlite(tmp_path / "fresh.db")
    try:
        results = apply_migrations(connection, now_ms=lambda: 123)
        assert [(result.version, result.name, result.applied) for result in results] == [
            (1, "current_schema", True)
        ]
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';"
            )
        }
        assert tables == CURRENT_TABLES
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE type='index' AND name NOT LIKE 'sqlite_%';"
            ).fetchone()[0]
            == 34
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='trigger';"
            ).fetchone()[0]
            == 44
        )
        assert connection.execute("PRAGMA foreign_key_check;").fetchall() == []

        replay = apply_migrations(connection, now_ms=lambda: 999)
        assert len(replay) == 1
        assert replay[0].applied is False
        receipt = connection.execute(
            "SELECT version, name, applied_at_ms FROM schema_migrations;"
        ).fetchone()
        assert tuple(receipt) == (1, "current_schema", 123)
    finally:
        connection.close()


def test_crlf_and_lf_share_one_logical_checksum(tmp_path: Path) -> None:
    migration_dir = tmp_path / "migrations"
    migration_dir.mkdir()
    raw = RUNTIME_MIGRATION.read_bytes().replace(b"\r\n", b"\n")
    (migration_dir / RUNTIME_MIGRATION.name).write_bytes(raw.replace(b"\n", b"\r\n"))
    connection = connect_sqlite(tmp_path / "crlf.db")
    try:
        apply_migrations(connection, migrations_dir=migration_dir, now_ms=lambda: 1)
        replay = apply_migrations(connection, now_ms=lambda: 2)
        assert replay[0].applied is False
    finally:
        connection.close()


def test_applied_checksum_and_name_drift_fail_closed(tmp_path: Path) -> None:
    connection = connect_sqlite(tmp_path / "drift.db")
    try:
        apply_migrations(connection, now_ms=lambda: 1)
        connection.execute("UPDATE schema_migrations SET checksum=? WHERE version=1;", ("0" * 64,))
        with pytest.raises(MigrationChecksumMismatchError):
            apply_migrations(connection, now_ms=lambda: 2)
        connection.execute(
            "UPDATE schema_migrations SET checksum=?, name='wrong' WHERE version=1;",
            (discover_migrations()[0].checksum,),
        )
        with pytest.raises(MigrationIntegrityError, match="name mismatch"):
            apply_migrations(connection, now_ms=lambda: 3)
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("filenames", "message"),
    [
        (("invalid.sql",), "invalid migration filename"),
        (("0001_one.sql", "0001_two.sql"), "duplicate migration version"),
        (("0001_empty.sql",), "empty migration"),
    ],
)
def test_invalid_migration_sources_are_rejected(
    tmp_path: Path,
    filenames: tuple[str, ...],
    message: str,
) -> None:
    migration_dir = tmp_path / "migrations"
    migration_dir.mkdir()
    for filename in filenames:
        (migration_dir / filename).write_text(
            "" if "empty" in filename else "SELECT 1;\n",
            encoding="utf-8",
        )
    with pytest.raises(MigrationDiscoveryError, match=message):
        discover_migrations(migration_dir)


def test_failed_followup_migration_rolls_back_without_partial_schema(tmp_path: Path) -> None:
    migration_dir = tmp_path / "migrations"
    migration_dir.mkdir()
    copyfile(RUNTIME_MIGRATION, migration_dir / RUNTIME_MIGRATION.name)
    (migration_dir / "0002_broken.sql").write_text(
        "BEGIN IMMEDIATE;\nCREATE TABLE partial(value TEXT);\nSELECT * FROM missing;\nCOMMIT;\n",
        encoding="utf-8",
    )
    connection = connect_sqlite(tmp_path / "broken.db")
    try:
        with pytest.raises(MigrationApplyError):
            apply_migrations(connection, migrations_dir=migration_dir, now_ms=lambda: 1)
        assert [
            tuple(row)
            for row in connection.execute(
                "SELECT version, name FROM schema_migrations ORDER BY version;"
            ).fetchall()
        ] == [(1, "current_schema")]
        assert (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='partial';"
            ).fetchone()
            is None
        )
    finally:
        connection.close()
