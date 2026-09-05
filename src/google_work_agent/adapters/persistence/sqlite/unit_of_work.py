"""SQLite transactional unit of work."""

import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import cast

from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.sqlite.initial_workflow_binding_writer import (
    SqliteInitialWorkflowBindingWriter,
)
from google_work_agent.adapters.persistence.sqlite.post_commit_trace_repository import (
    PostCommitTraceEventRepository,
)
from google_work_agent.adapters.persistence.sqlite.repositories.action_repository import (
    SqliteActionRepository,
)
from google_work_agent.adapters.persistence.sqlite.repositories.approval_repository import (
    SqliteApprovalRepository,
)
from google_work_agent.adapters.persistence.sqlite.repositories.audit_event_repository import (
    SqliteAuditEventRepository,
)
from google_work_agent.adapters.persistence.sqlite.repositories.command_receipt_repository import (
    SqliteCommandReceiptRepository,
)
from google_work_agent.adapters.persistence.sqlite.repositories.conversation_repository import (
    SqliteConversationRepository,
)
from google_work_agent.adapters.persistence.sqlite.repositories.evidence_repository import (
    SqliteEvidenceRepository,
)
from google_work_agent.adapters.persistence.sqlite.repositories.message_repository import (
    SqliteMessageRepository,
)
from google_work_agent.adapters.persistence.sqlite.repositories.plan_repository import (
    SqlitePlanRepository,
)
from google_work_agent.adapters.persistence.sqlite.repositories.recovery_repository import (
    SqliteRecoveryRepository,
)
from google_work_agent.adapters.persistence.sqlite.repositories.resource_ref_repository import (
    SqliteResourceRefRepository,
)
from google_work_agent.adapters.persistence.sqlite.repositories.retention_repository import (
    SqliteRetentionRepository,
)
from google_work_agent.adapters.persistence.sqlite.repositories.run_repository import (
    SqliteRunRepository,
)
from google_work_agent.adapters.persistence.sqlite.repositories.verification_repository import (
    SqliteVerificationRepository,
)
from google_work_agent.adapters.persistence.sqlite.repositories.workflow_handoff_repository import (
    SqliteWorkflowHandoffRepository,
)
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork

from .repositories.execution_attempt_repository import (
    SqliteExecutionAttemptRepository,
)


class SqliteUnitOfWork:
    """Context-managed SQLite transaction boundary for commands or queries."""

    def __init__(
        self,
        database_path: Path,
        *,
        now_ms: Callable[[], int] | None = None,
        read_only: bool = False,
        environment: str = "test",
        release_version: str = "dev",
    ) -> None:
        self._database_path = database_path
        self._now_ms = now_ms or (lambda: int(time.time() * 1000))
        self._read_only = read_only
        self._environment = environment
        self._release_version = release_version
        self._connection: sqlite3.Connection | None = None
        self._committed = False

    def __enter__(self) -> "SqliteUnitOfWork":
        connection = connect_sqlite(self._database_path)
        if self._read_only:
            connection.execute("PRAGMA query_only = ON;")
            connection.execute("BEGIN;")
        else:
            connection.execute("BEGIN IMMEDIATE;")
        self._connection = connection
        self.conversations = SqliteConversationRepository(connection)
        self.runs = SqliteRunRepository(connection)
        self.messages = SqliteMessageRepository(connection)
        self.command_receipts = SqliteCommandReceiptRepository(connection)
        self.plans = SqlitePlanRepository(connection)
        self.actions = SqliteActionRepository(connection)
        self.resource_refs = SqliteResourceRefRepository(connection)
        self.evidence = SqliteEvidenceRepository(connection)
        self.approvals = SqliteApprovalRepository(connection)
        self.execution_attempts = SqliteExecutionAttemptRepository(connection)
        self.verifications = SqliteVerificationRepository(connection)
        self.audits = SqliteAuditEventRepository(
            connection, environment=self._environment, release_version=self._release_version,
        )
        self.traces = PostCommitTraceEventRepository(
            connection, environment=self._environment, release_version=self._release_version,
        )
        self.workflow_handoffs = SqliteWorkflowHandoffRepository(connection, now_ms=self._now_ms)
        self.recovery_contexts = SqliteRecoveryRepository(connection, now_ms=self._now_ms)
        self.retention = SqliteRetentionRepository(connection)
        self.workflow_bindings = SqliteInitialWorkflowBindingWriter(connection)
        return self

    def commit(self) -> None:
        if self._connection is None:
            raise RuntimeError("unit of work is not active")
        self._connection.execute("COMMIT;")
        self._committed = True
        if isinstance(self.traces, PostCommitTraceEventRepository):
            self.traces.flush_after_commit()

    def rollback(self) -> None:
        if isinstance(self.traces, PostCommitTraceEventRepository):
            self.traces.discard_pending()
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
    database_path: Path, *, now_ms: Callable[[], int] | None = None,
    environment: str = "test", release_version: str = "dev",
) -> Callable[[], UnitOfWork]:
    def _factory() -> SqliteUnitOfWork:
        return SqliteUnitOfWork(
            database_path, now_ms=now_ms, environment=environment, release_version=release_version,
        )

    return cast(Callable[[], UnitOfWork], _factory)


def sqlite_read_unit_of_work_factory(
    database_path: Path, *, now_ms: Callable[[], int] | None = None,
    environment: str = "test", release_version: str = "dev",
) -> Callable[[], UnitOfWork]:
    """Build snapshot-consistent query UoWs without acquiring a writer lock."""

    def _factory() -> SqliteUnitOfWork:
        return SqliteUnitOfWork(
            database_path, now_ms=now_ms, read_only=True,
            environment=environment, release_version=release_version,
        )

    return cast(Callable[[], UnitOfWork], _factory)
