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

__all__ = [
    "MigrationFile",
    "MigrationResult",
    "apply_migrations",
    "calculate_migration_checksum",
    "connect_sqlite",
    "discover_migrations",
    "normalize_migration_bytes",
]
