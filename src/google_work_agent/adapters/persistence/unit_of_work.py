"""SQLite transactional unit of work."""

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import cast

from google_work_agent.adapters.persistence.cancel_intent_repository import (
    CancelIntentCommandReceiptRepository,
)
from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.confirmation_run_repository import (
    SQLiteConfirmationRunRepository,
)
from google_work_agent.adapters.persistence.connector_identity import (
    ConnectorAwareActionRepository,
    ConnectorAwareResourceRefRepository,
)
from google_work_agent.adapters.persistence.corrective_plan_repository import (
    CorrectiveAwareSQLitePlanRepository,
)
from google_work_agent.adapters.persistence.repositories import (
    SQLiteActionDependencyRepository,
    SQLiteApprovalRepository,
    SQLiteConversationRepository,
    SQLiteEvidenceRepository,
    SQLiteExecutionAttemptRepository,
    SQLiteMessageRepository,
    SQLiteVerificationRepository,
)
from google_work_agent.adapters.persistence.secret_boundary import (
    SecretBoundaryAuditRepository,
    SecretBoundaryTraceRepository,
)
from google_work_agent.ports import UnitOfWork


class SQLiteUnitOfWork:
    """Context-managed SQLite transaction boundary using BEGIN IMMEDIATE."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._connection: sqlite3.Connection | None = None
        self._committed = False

    def __enter__(self) -> "SQLiteUnitOfWork":
        connection = connect_sqlite(self._database_path)
        connection.execute("BEGIN IMMEDIATE;")
        self._connection = connection
        self.conversations = SQLiteConversationRepository(connection)
        self.runs = SQLiteConfirmationRunRepository(connection)
        self.messages = SQLiteMessageRepository(connection)
        self.command_receipts = CancelIntentCommandReceiptRepository(connection)
        self.plans = CorrectiveAwareSQLitePlanRepository(connection)
        self.actions = ConnectorAwareActionRepository(connection)
        self.resource_refs = ConnectorAwareResourceRefRepository(connection)
        self.evidence = SQLiteEvidenceRepository(connection)
        self.action_dependencies = SQLiteActionDependencyRepository(connection)
        self.approvals = SQLiteApprovalRepository(connection)
        self.execution_attempts = SQLiteExecutionAttemptRepository(connection)
        self.verifications = SQLiteVerificationRepository(connection)
        self.audits = SecretBoundaryAuditRepository(connection)
        self.traces = SecretBoundaryTraceRepository(connection)
        return self

    def commit(self) -> None:
        if self._connection is None:
            raise RuntimeError("unit of work is not active")
        self._connection.execute("COMMIT;")
        self._committed = True

    def rollback(self) -> None:
        if self._connection is not None and self._connection.in_transaction:
            self._connection.execute("ROLLBACK;")

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        exc_tb: object | None,
    ) -> None:
        try:
            if not self._committed:
                self.rollback()
        finally:
            if self._connection is not None:
                self._connection.close()
                self._connection = None


def sqlite_unit_of_work_factory(database_path: Path) -> Callable[[], UnitOfWork]:
    """Create a zero-argument unit-of-work factory bound to one database path."""

    def _factory() -> SQLiteUnitOfWork:
        return SQLiteUnitOfWork(database_path)

    return cast(Callable[[], UnitOfWork], _factory)
