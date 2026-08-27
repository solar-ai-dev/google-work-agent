"""Persistence adapter package."""

from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.migration import (
    MigrationFile,
    MigrationResult,
    apply_migrations,
    calculate_migration_checksum,
    discover_migrations,
    normalize_migration_bytes,
)
from google_work_agent.adapters.persistence.sqlite.unit_of_work import (
    sqlite_unit_of_work_factory,
)

__all__ = [
    "MigrationFile",
    "MigrationResult",
    "apply_migrations",
    "calculate_migration_checksum",
    "connect_sqlite",
    "discover_migrations",
    "normalize_migration_bytes",
    "sqlite_unit_of_work_factory",
]
