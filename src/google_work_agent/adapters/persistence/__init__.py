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
from google_work_agent.adapters.persistence.sqlite.repositories.action_dependency_repository import (  # noqa: E501
    SQLiteActionDependencyRepository,
)
from google_work_agent.adapters.persistence.sqlite.repositories.action_repository import (
    SQLiteActionRepository,
)
from google_work_agent.adapters.persistence.sqlite.repositories.approval_repository import (
    SQLiteApprovalRepository,
)
from google_work_agent.adapters.persistence.sqlite.repositories.audit_repository import (
    SQLiteAuditRepository,
)
from google_work_agent.adapters.persistence.sqlite.repositories.command_receipt_repository import (
    SQLiteCommandReceiptRepository,
)
from google_work_agent.adapters.persistence.sqlite.repositories.evidence_repository import (
    SQLiteEvidenceRepository,
)
from google_work_agent.adapters.persistence.sqlite.repositories.execution_attempt_repository import (  # noqa: E501
    SQLiteExecutionAttemptRepository,
)
from google_work_agent.adapters.persistence.sqlite.repositories.plan_repository import (
    SQLitePlanRepository,
)
from google_work_agent.adapters.persistence.sqlite.repositories.run_repository import (
    SQLiteRunRepository,
)
from google_work_agent.adapters.persistence.sqlite.repositories.trace_repository import (
    SQLiteTraceRepository,
)
from google_work_agent.adapters.persistence.sqlite.repositories.verification_repository import (
    SQLiteVerificationRepository,
)
from google_work_agent.adapters.persistence.sqlite.unit_of_work import (
    SqliteUnitOfWork,
    sqlite_unit_of_work_factory,
)

__all__ = [
    "MigrationFile",
    "MigrationResult",
    "SQLiteActionDependencyRepository",
    "SQLiteActionRepository",
    "SQLiteApprovalRepository",
    "SQLiteAuditRepository",
    "SQLiteCommandReceiptRepository",
    "SQLiteEvidenceRepository",
    "SQLiteExecutionAttemptRepository",
    "SQLitePlanRepository",
    "SQLiteRunRepository",
    "SQLiteTraceRepository",
    "SQLiteVerificationRepository",
    "SqliteUnitOfWork",
    "apply_migrations",
    "calculate_migration_checksum",
    "connect_sqlite",
    "discover_migrations",
    "normalize_migration_bytes",
    "sqlite_unit_of_work_factory",
]
