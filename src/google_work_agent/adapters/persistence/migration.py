"""SQLite migration discovery and application."""

import re
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from importlib import resources
from pathlib import Path

from google_work_agent.adapters.persistence.errors import (
    MigrationApplyError,
    MigrationChecksumMismatchError,
    MigrationDiscoveryError,
    MigrationIntegrityError,
)

_MIGRATION_FILENAME = re.compile(r"^(?P<version>[0-9]{4})_(?P<name>[A-Za-z0-9_]+)\.sql$")
_MIGRATIONS_PACKAGE = "google_work_agent.adapters.persistence.migrations"


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
    """Apply pending SQLite migrations atomically, one migration per transaction."""
    clock = now_ms or _system_now_ms
    migrations = discover_migrations(migrations_dir)
    applied = _read_applied_migrations(connection)
    results: list[MigrationResult] = []

    for migration in migrations:
        applied_row = applied.get(migration.version)
        if applied_row is not None:
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

    return tuple(results)


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
    pragma_statements = [statement for statement in statements if _is_pragma_statement(statement)]
    ddl_statements = [statement for statement in statements if not _is_pragma_statement(statement)]

    try:
        for statement in pragma_statements:
            connection.execute(statement)

        connection.execute("BEGIN IMMEDIATE;")
        for statement in ddl_statements:
            connection.execute(statement)
        connection.execute(
            """
            INSERT INTO schema_migrations (version, name, checksum, applied_at_ms)
            VALUES (?, ?, ?, ?);
            """,
            (migration.version, migration.name, migration.checksum, applied_at_ms),
        )
        connection.execute("COMMIT;")
    except sqlite3.Error as exc:
        if connection.in_transaction:
            connection.execute("ROLLBACK;")
        raise MigrationApplyError(
            f"migration apply failed: version={migration.version} name={migration.name}"
        ) from exc
    finally:
        connection.execute("PRAGMA foreign_keys = ON;")


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


def _system_now_ms() -> int:
    return time.time_ns() // 1_000_000
