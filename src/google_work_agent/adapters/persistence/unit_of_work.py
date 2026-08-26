"""SQLite transactional unit of work."""

import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import cast

from google_work_agent.adapters.persistence.connection import connect_sqlite
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
from google_work_agent.adapters.persistence.sqlite.repositories.conversation_repository import (
    SqliteConversationRepository,
)
from google_work_agent.adapters.persistence.sqlite.repositories.evidence_repository import (
    SQLiteEvidenceRepository,
)
from google_work_agent.adapters.persistence.sqlite.repositories.execution_attempt_repository import (  # noqa: E501
    SQLiteExecutionAttemptRepository,
)
from google_work_agent.adapters.persistence.sqlite.repositories.message_repository import (
    SqliteMessageRepository,
)
from google_work_agent.adapters.persistence.sqlite.repositories.plan_repository import (
    SQLitePlanRepository,
)
from google_work_agent.adapters.persistence.sqlite.repositories.resource_ref_repository import (
    SqliteResourceRefRepository,
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
from google_work_agent.adapters.persistence.sqlite.repositories.workflow_handoff_repository import (
    SqliteWorkflowHandoffRepository,
)
from google_work_agent.adapters.system.sqlite_checkpoint import SqliteCheckpointAdapter
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


class SQLiteUnitOfWork:
    """Context-managed SQLite transaction boundary using BEGIN IMMEDIATE."""

    def __init__(self, database_path: Path, *, now_ms: Callable[[], int] | None = None) -> None:
        self._database_path = database_path
        self._now_ms = now_ms or (lambda: int(time.time() * 1000))
        self._connection: sqlite3.Connection | None = None
        self._committed = False

    def __enter__(self) -> "SQLiteUnitOfWork":
        connection = connect_sqlite(self._database_path)
        connection.execute("BEGIN IMMEDIATE;")
        self._connection = connection
        self.conversations = SqliteConversationRepository(connection)
        self.runs = SQLiteRunRepository(connection)
        self.messages = SqliteMessageRepository(connection)
        self.command_receipts = SQLiteCommandReceiptRepository(connection)
        self.plans = SQLitePlanRepository(connection)
        self.actions = SQLiteActionRepository(connection)
        self.resource_refs = SqliteResourceRefRepository(connection)
        self.evidence = SQLiteEvidenceRepository(connection)
        self.action_dependencies = SQLiteActionDependencyRepository(connection)
        self.approvals = SQLiteApprovalRepository(connection)
        self.execution_attempts = SQLiteExecutionAttemptRepository(connection)
        self.verifications = SQLiteVerificationRepository(connection)
        self.audits = SQLiteAuditRepository(connection)
        self.traces = SQLiteTraceRepository(connection)
        self.workflow_handoffs = SqliteWorkflowHandoffRepository(connection, now_ms=self._now_ms)
        self.checkpoints = SqliteCheckpointAdapter.for_transaction(connection, now_ms=self._now_ms)
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
        self, exc_type: type[BaseException] | None, exc: BaseException | None, exc_tb: object | None
    ) -> None:
        try:
            if not self._committed:
                self.rollback()
        finally:
            if self._connection is not None:
                self._connection.close()
                self._connection = None


def sqlite_unit_of_work_factory(
    database_path: Path, *, now_ms: Callable[[], int] | None = None
) -> Callable[[], UnitOfWork]:
    def _factory() -> SQLiteUnitOfWork:
        return SQLiteUnitOfWork(database_path, now_ms=now_ms)

    return cast(Callable[[], UnitOfWork], _factory)
