"""SQLite migration discovery and application."""

import re
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from importlib import resources
from pathlib import Path

from google_work_agent.adapters.persistence.persistence_exceptions import (
    MigrationApplyError,
    MigrationChecksumMismatchError,
    MigrationDiscoveryError,
    MigrationIntegrityError,
)

_MIGRATION_FILENAME = re.compile(r"^(?P<version>[0-9]{4})_(?P<name>[A-Za-z0-9_]+)\.sql$")
_MIGRATIONS_PACKAGE = "google_work_agent.adapters.persistence.migrations"
_SUPPORTED_LEGACY_V18 = {
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
    11: (
        "recovery_context",
        "6ea69233b063b24946d04946c17ba19db0cabc0ebce9aba8fa2b2cfc3830a843",
    ),
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


@dataclass(frozen=True, slots=True)
class MigrationFile:
    """A migration file discovered from package resources or a test directory."""

    version: int
    name: str
    path: Path
    checksum: str


@dataclass(frozen=True, slots=True)
class MigrationResult:
    """Result of checking or applying a migration."""

    version: int
    name: str
    checksum: str
    applied: bool


@dataclass(frozen=True, slots=True)
class _MigrationExecutionPlan:
    """Preserve the migration-authored PRAGMA/transaction lifecycle."""

    pre_transaction_statements: tuple[str, ...]
    begin_statement: str
    transaction_statements: tuple[str, ...]
    commit_statement: str
    post_transaction_statements: tuple[str, ...]


def normalize_migration_bytes(raw: bytes) -> bytes:
    """Normalize migration bytes for logical checksum calculation."""
    return raw.replace(b"\r\n", b"\n")


def calculate_migration_checksum(raw: bytes) -> str:
    """Calculate the SHA-256 checksum from normalized migration bytes."""
    return sha256(normalize_migration_bytes(raw)).hexdigest()


def discover_migrations(migrations_dir: Path | None = None) -> tuple[MigrationFile, ...]:
    """Discover, validate, and version-sort migration files."""
    entries = (
        _read_directory_migrations(migrations_dir)
        if migrations_dir is not None
        else _read_package_migrations()
    )
    migrations: list[MigrationFile] = []
    seen_versions: dict[int, str] = {}

    for path, raw in entries:
        match = _MIGRATION_FILENAME.fullmatch(path.name)
        if match is None:
            raise MigrationDiscoveryError(f"invalid migration filename: {path.name}")

        version = int(match.group("version"))
        name = match.group("name")
        if version <= 0:
            raise MigrationDiscoveryError(f"invalid migration version: {path.name}")
        if not raw.strip():
            raise MigrationDiscoveryError(f"empty migration: version={version} name={name}")

        previous_name = seen_versions.get(version)
        if previous_name is not None:
            raise MigrationDiscoveryError(
                f"duplicate migration version: version={version} name={name}"
            )
        seen_versions[version] = name
        migrations.append(
            MigrationFile(
                version=version,
                name=name,
                path=path,
                checksum=calculate_migration_checksum(raw),
            )
        )

    return tuple(sorted(migrations, key=lambda migration: migration.version))


def apply_migrations(
    connection: sqlite3.Connection,
    migrations_dir: Path | None = None,
    now_ms: Callable[[], int] | None = None,
) -> tuple[MigrationResult, ...]:
    """Apply pending migrations, then gate readiness on whole-database integrity.

    Each migration may perform its own post-migration ``foreign_key_check``.
    That check is migration-local.  The explicit startup gate below is separate:
    after *all* migrations are current, run ``quick_check`` and then a full
    ``foreign_key_check`` before the caller may proceed toward READY.
    """
    clock = now_ms or _system_now_ms
    migrations = discover_migrations(migrations_dir)
    applied = _read_applied_migrations(connection)
    supported_legacy_v18 = migrations_dir is None and _is_supported_legacy_v18(applied)
    results: list[MigrationResult] = []

    for migration in migrations:
        applied_row = applied.get(migration.version)
        if applied_row is not None:
            if not (supported_legacy_v18 and migration.version == 1):
                _validate_applied_migration(migration, applied_row)
            results.append(
                MigrationResult(
                    version=migration.version,
                    name=migration.name,
                    checksum=migration.checksum,
                    applied=False,
                )
            )
            continue

        raw = _read_migration_bytes(migration, migrations_dir)
        _apply_single_migration(connection, migration, raw, clock())
        results.append(
            MigrationResult(
                version=migration.version,
                name=migration.name,
                checksum=migration.checksum,
                applied=True,
            )
        )
        applied[migration.version] = (migration.name, migration.checksum)

    verify_startup_database_integrity(connection)
    return tuple(results)


def _is_supported_legacy_v18(applied: dict[int, tuple[str, str]]) -> bool:
    """Recognize only the exact last supported pre-squash installed baseline."""

    legacy_rows = {version: value for version, value in applied.items() if version <= 18}
    return legacy_rows == _SUPPORTED_LEGACY_V18 and set(applied).issubset({*range(1, 19), 19})


def verify_startup_database_integrity(connection: sqlite3.Connection) -> None:
    """Fail closed unless SQLite quick/FK integrity is clean after migrations."""
    quick_rows = connection.execute("PRAGMA quick_check;").fetchall()
    if len(quick_rows) != 1 or str(quick_rows[0][0]).lower() != "ok":
        detail = "; ".join(str(row[0]) for row in quick_rows[:8]) or "no result"
        raise MigrationIntegrityError(f"startup quick_check failed: {detail}")

    foreign_key_rows = connection.execute("PRAGMA foreign_key_check;").fetchall()
    if foreign_key_rows:
        sample = "; ".join(
            ":".join(str(value) for value in tuple(row)) for row in foreign_key_rows[:8]
        )
        raise MigrationIntegrityError(f"startup foreign_key_check failed: {sample}")


def _read_directory_migrations(migrations_dir: Path) -> tuple[tuple[Path, bytes], ...]:
    if not migrations_dir.exists() or not migrations_dir.is_dir():
        raise MigrationDiscoveryError("migration directory is not available")

    entries: list[tuple[Path, bytes]] = []
    for path in sorted(migrations_dir.iterdir()):
        if path.name == "__init__.py" or path.name == "__pycache__":
            continue
        if path.is_dir() or path.suffix != ".sql":
            raise MigrationDiscoveryError(f"unsupported migration entry: {path.name}")
        entries.append((path, path.read_bytes()))
    return tuple(entries)


def _read_package_migrations() -> tuple[tuple[Path, bytes], ...]:
    entries: list[tuple[Path, bytes]] = []
    for resource in sorted(
        resources.files(_MIGRATIONS_PACKAGE).iterdir(), key=lambda item: item.name
    ):
        if resource.name == "__init__.py" or resource.name == "__pycache__":
            continue
        if not resource.is_file() or not resource.name.endswith(".sql"):
            raise MigrationDiscoveryError(f"unsupported migration entry: {resource.name}")
        entries.append((Path(str(resource)), resource.read_bytes()))
    return tuple(entries)


def _read_applied_migrations(connection: sqlite3.Connection) -> dict[int, tuple[str, str]]:
    exists = connection.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = 'schema_migrations';
        """
    ).fetchone()
    if exists is None:
        return {}

    rows = connection.execute(
        "SELECT version, name, checksum FROM schema_migrations ORDER BY version;"
    ).fetchall()
    applied: dict[int, tuple[str, str]] = {}
    for row in rows:
        version = int(row["version"])
        if version in applied:
            raise MigrationIntegrityError(f"duplicate applied migration: version={version}")
        applied[version] = (str(row["name"]), str(row["checksum"]))
    return applied


def _read_migration_bytes(migration: MigrationFile, migrations_dir: Path | None) -> bytes:
    if migrations_dir is not None:
        return migration.path.read_bytes()
    return resources.files(_MIGRATIONS_PACKAGE).joinpath(migration.path.name).read_bytes()


def _validate_applied_migration(
    migration: MigrationFile,
    applied_row: tuple[str, str],
) -> None:
    applied_name, applied_checksum = applied_row
    if applied_name != migration.name:
        raise MigrationIntegrityError(
            f"migration name mismatch: version={migration.version} name={migration.name}"
        )
    if applied_checksum != migration.checksum:
        raise MigrationChecksumMismatchError(
            f"migration checksum mismatch: version={migration.version} name={migration.name}"
        )


def _apply_single_migration(
    connection: sqlite3.Connection,
    migration: MigrationFile,
    raw: bytes,
    applied_at_ms: int,
) -> None:
    statements = _split_sql_statements(raw.decode("utf-8"))
    execution = _build_migration_execution_plan(statements)

    try:
        for statement in execution.pre_transaction_statements:
            _execute_outside_transaction_statement(connection, migration, statement)

        connection.execute(execution.begin_statement)
        for statement in execution.transaction_statements:
            connection.execute(statement)
        connection.execute(
            """
            INSERT INTO schema_migrations (version, name, checksum, applied_at_ms)
            VALUES (?, ?, ?, ?);
            """,
            (migration.version, migration.name, migration.checksum, applied_at_ms),
        )
        connection.execute(execution.commit_statement)

        for statement in execution.post_transaction_statements:
            _execute_outside_transaction_statement(connection, migration, statement)
    except sqlite3.Error as exc:
        if connection.in_transaction:
            connection.execute("ROLLBACK;")
        raise MigrationApplyError(
            f"migration apply failed: version={migration.version} name={migration.name}"
        ) from exc
    finally:
        connection.execute("PRAGMA foreign_keys = ON;")


def _build_migration_execution_plan(statements: tuple[str, ...]) -> _MigrationExecutionPlan:
    control_indexes = [
        index
        for index, statement in enumerate(statements)
        if _is_transaction_control_statement(statement)
    ]
    if control_indexes:
        controls = tuple(_statement_keyword(statements[index]) for index in control_indexes)
        if controls != ("BEGIN", "COMMIT"):
            raise MigrationDiscoveryError(
                "explicit migration transaction must contain exactly BEGIN then COMMIT"
            )
        begin_index, commit_index = control_indexes
        pre_transaction = statements[:begin_index]
        transaction_statements = statements[begin_index + 1 : commit_index]
        post_transaction = statements[commit_index + 1 :]
        if not all(_is_pragma_statement(statement) for statement in pre_transaction):
            raise MigrationDiscoveryError(
                "only PRAGMA statements may precede an explicit migration BEGIN"
            )
        if not all(_is_pragma_statement(statement) for statement in post_transaction):
            raise MigrationDiscoveryError(
                "only PRAGMA statements may follow an explicit migration COMMIT"
            )
        return _MigrationExecutionPlan(
            pre_transaction_statements=pre_transaction,
            begin_statement=statements[begin_index],
            transaction_statements=transaction_statements,
            commit_statement=statements[commit_index],
            post_transaction_statements=post_transaction,
        )

    leading_pragma_count = 0
    for statement in statements:
        if not _is_pragma_statement(statement):
            break
        leading_pragma_count += 1

    trailing_pragma_start = len(statements)
    while trailing_pragma_start > leading_pragma_count and _is_pragma_statement(
        statements[trailing_pragma_start - 1]
    ):
        trailing_pragma_start -= 1

    transaction_statements = statements[leading_pragma_count:trailing_pragma_start]
    if any(_is_pragma_statement(statement) for statement in transaction_statements):
        raise MigrationDiscoveryError(
            "mid-migration PRAGMA requires explicit BEGIN/COMMIT lifecycle markers"
        )

    return _MigrationExecutionPlan(
        pre_transaction_statements=statements[:leading_pragma_count],
        begin_statement="BEGIN IMMEDIATE;",
        transaction_statements=transaction_statements,
        commit_statement="COMMIT;",
        post_transaction_statements=statements[trailing_pragma_start:],
    )


def _execute_outside_transaction_statement(
    connection: sqlite3.Connection,
    migration: MigrationFile,
    statement: str,
) -> None:
    if _is_foreign_key_check_statement(statement):
        if connection.execute(statement).fetchall():
            raise MigrationIntegrityError(
                "migration foreign key check failed: "
                f"version={migration.version} name={migration.name}"
            )
        return
    connection.execute(statement)


def _split_sql_statements(sql: str) -> tuple[str, ...]:
    statements: list[str] = []
    buffer = ""
    for line in sql.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            if statement:
                statements.append(statement)
            buffer = ""
    if buffer.strip():
        raise MigrationDiscoveryError("incomplete SQL statement")
    return tuple(statements)


def _is_pragma_statement(statement: str) -> bool:
    for line in statement.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        return stripped.upper().startswith("PRAGMA ")
    return False


def _is_transaction_control_statement(statement: str) -> bool:
    keyword = _statement_keyword(statement)
    return keyword in {"BEGIN", "COMMIT", "ROLLBACK"}


def _is_foreign_key_check_statement(statement: str) -> bool:
    return _statement_keyword(statement) == "PRAGMA FOREIGN_KEY_CHECK"


def _statement_keyword(statement: str) -> str:
    for line in statement.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        normalized = stripped.rstrip(";").upper()
        if normalized.startswith("PRAGMA FOREIGN_KEY_CHECK"):
            return "PRAGMA FOREIGN_KEY_CHECK"
        if normalized.startswith("PRAGMA "):
            return "PRAGMA"
        if normalized.startswith("BEGIN"):
            return "BEGIN"
        if normalized.startswith("COMMIT"):
            return "COMMIT"
        if normalized.startswith("ROLLBACK"):
            return "ROLLBACK"
        return normalized.split(maxsplit=1)[0]
    return ""


def _system_now_ms() -> int:
    return time.time_ns() // 1_000_000
