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
LEGACY_ADOPTION_MIGRATION = (
    ROOT / "src/google_work_agent/adapters/persistence/migrations/0019_legacy_v18_adoption.sql"
)
DOCUMENTATION_LEGACY_ADOPTION_MIGRATION = (
    ROOT / "docs/database/migrations/0019_legacy_v18_adoption.sql"
)

LEGACY_V18_RECEIPTS = {
    1: ("initial", "77386baca1badadd6a79860823250836f7a6464e7f01bd865c3a84af094aa928"),
    2: (
        "action_effect_send_delete",
        "0cbd43fbaa351b19540128f860c4e88e827b263329b102cbe9016c1190145624",
    ),
    3: ("action_cancelled", "d56a55a7fd4f5cec5d34705bf1cb09c218d22b762956b38af79a983faa033403"),
    4: ("plan_review_gate", "d12a4fc67101c3d14ff0ec57175c9d19ba765fe0eab41e0d5b3875b48b388f95"),
    5: (
        "cross_aggregate_invariants",
        "ff2508e23c238a1b7bb3ec604031f7598cceff2285378767b61651590f5b109b",
    ),
    6: (
        "plan_aggregate_invariants",
        "dec3bc8f018f7b4997e27dd6c45b25788c59279ea7717a3e0ae6c84d57caefd2",
    ),
    7: (
        "connector_neutral_persistence",
        "a9ea291c71d1c7ee1bdf07d31dd1a7b06a919c184cfd2e9dfa1f110fdf55bde8",
    ),
    8: (
        "resource_ref_connector_identity",
        "f45da38077393a0073eae6414e76c2f03cd24f85db35b08b386d71541fe538c6",
    ),
    9: (
        "workflow_handoff_outbox",
        "6188c6868c98c019b545fa89a4dc7f6772d02f6e626ce0ba38bf1cd7b635103b",
    ),
    10: (
        "plan_review_disposition",
        "df069780c8398b6811a43e3e457586606f0e529b4e7270f2d22a9650ed512358",
    ),
    11: ("recovery_context", "6ea69233b063b24946d04946c17ba19db0cabc0ebce9aba8fa2b2cfc3830a843"),
    12: (
        "recovery_context_currentness",
        "4ec30705a9049deebd3b9132f5f3fde69854bb295e79c646e102c04e0b4f3b6b",
    ),
    13: (
        "resource_ref_registry_type",
        "45fd1a32daea1e95429639d7f7755305479ac4bd917a7534c1c29eb51efd53c1",
    ),
    14: (
        "run_terminal_result_kind",
        "35b77895f5d5507bf2ed5e261437293ccdaf88b181ba3db76b62016c8b1f523f",
    ),
    15: (
        "canonical_final_defense",
        "3f95d2d3831b2de071efc2fc09a134c93caf7216d617977cf493fa55e2b21460",
    ),
    16: (
        "persistence_final_defense",
        "412481bf20945555e935d21d95011e5823136e8930495b623a5888bd0a126c3f",
    ),
    17: (
        "recovery_context_reason_matrix",
        "250514cd7b5ef8f70065b7d288b2d25a716eda731babe4301278e63006b6f7aa",
    ),
    18: (
        "initial_workflow_binding",
        "d3aaaef9da63c2d0e89edc7ca67936d0ef06c0ea1744d257a79335598e33e4ec",
    ),
}

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


def test_runtime_and__documentation_expose__identical_forward_migrations() -> None:
    runtime = RUNTIME_MIGRATION.read_bytes().replace(b"\r\n", b"\n")
    documented = DOCUMENTATION_MIGRATION.read_bytes().replace(b"\r\n", b"\n")

    assert documented == runtime
    assert DOCUMENTATION_LEGACY_ADOPTION_MIGRATION.read_bytes().replace(
        b"\r\n", b"\n"
    ) == LEGACY_ADOPTION_MIGRATION.read_bytes().replace(b"\r\n", b"\n")
    migrations = discover_migrations()
    assert [(item.version, item.name) for item in migrations] == [
        (1, "current_schema"),
        (19, "legacy_v18_adoption"),
    ]
    assert migrations[0].checksum == calculate_migration_checksum(runtime)


def test_fresh_database_has__exact_current_tables__and_safety_objects(tmp_path: Path) -> None:
    connection = connect_sqlite(tmp_path / "fresh.db")
    try:
        results = apply_migrations(connection, now_ms=lambda: 123)
        assert [(result.version, result.name, result.applied) for result in results] == [
            (1, "current_schema", True),
            (19, "legacy_v18_adoption", True),
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
        assert len(replay) == 2
        assert all(result.applied is False for result in replay)
        receipt = connection.execute(
            "SELECT version, name, applied_at_ms FROM schema_migrations;"
        ).fetchone()
        assert tuple(receipt) == (1, "current_schema", 123)
    finally:
        connection.close()


def test_crlf_and__lf_share__one_logical_checksum(tmp_path: Path) -> None:
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


def test_applied_checksum__and_name__drift_fail_closed(tmp_path: Path) -> None:
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
def test_invalid_migration__sources_are__rejected(
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


def test_failed_followup__migration_rolls_back__without_partial_schema(tmp_path: Path) -> None:
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


def test_exact_legacy_v18__receipts_are_adopted__without_rewriting_history(
    tmp_path: Path,
) -> None:
    connection = connect_sqlite(tmp_path / "legacy-v18.db")
    try:
        apply_migrations(connection, now_ms=lambda: 1)
        connection.execute("DELETE FROM schema_migrations;")
        connection.executemany(
            "INSERT INTO schema_migrations (version, name, checksum, applied_at_ms) "
            "VALUES (?, ?, ?, ?);",
            [
                (version, name, checksum, version)
                for version, (name, checksum) in LEGACY_V18_RECEIPTS.items()
            ],
        )
        connection.execute(
            "INSERT INTO google_accounts (id, email, display_name, connected_at_ms) "
            "VALUES ('account-legacy', 'legacy@example.com', 'Legacy', 1);"
        )

        results = apply_migrations(connection, now_ms=lambda: 20)

        assert [(result.version, result.applied) for result in results] == [
            (1, False),
            (19, True),
        ]
        assert (
            connection.execute(
                "SELECT email FROM google_accounts WHERE id='account-legacy';"
            ).fetchone()[0]
            == "legacy@example.com"
        )
        receipts = connection.execute(
            "SELECT version, name, checksum FROM schema_migrations ORDER BY version;"
        ).fetchall()
        assert [int(row[0]) for row in receipts] == [*range(1, 19), 19]
    finally:
        connection.close()


def test_legacy_v18__checksum_drift__remains_fail_closed(tmp_path: Path) -> None:
    connection = connect_sqlite(tmp_path / "legacy-drift.db")
    try:
        apply_migrations(connection, now_ms=lambda: 1)
        connection.execute(
            "UPDATE schema_migrations SET name='initial', checksum=? WHERE version=1;",
            ("0" * 64,),
        )
        with pytest.raises(MigrationIntegrityError, match="name mismatch"):
            apply_migrations(connection, now_ms=lambda: 2)
    finally:
        connection.close()
