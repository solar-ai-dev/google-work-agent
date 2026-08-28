"""Fault-injecting SQLite wrappers for transactional tests."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, cast

from google_work_agent.adapters.persistence.connection import connect_sqlite
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
from google_work_agent.adapters.persistence.sqlite.repositories.execution_attempt_repository import (  # noqa: E501
    SqliteExecutionAttemptRepository,
)
from google_work_agent.adapters.persistence.sqlite.repositories.message_repository import (
    SqliteMessageRepository,
)
from google_work_agent.adapters.persistence.sqlite.repositories.plan_repository import (
    SqlitePlanRepository,
)
from google_work_agent.adapters.persistence.sqlite.repositories.resource_ref_repository import (
    SqliteResourceRefRepository,
)
from google_work_agent.adapters.persistence.sqlite.repositories.run_repository import (
    SqliteRunRepository,
)
from google_work_agent.adapters.persistence.sqlite.repositories.trace_event_repository import (
    SqliteTraceEventRepository,
)
from google_work_agent.adapters.persistence.sqlite.repositories.verification_repository import (
    SqliteVerificationRepository,
)
from google_work_agent.ports import UnitOfWork


class SQLiteFaultStage(StrEnum):
    """Supported SQLite fault injection stages."""

    AFTER_BEGIN = "AFTER_BEGIN"
    AFTER_FIRST_INSERT = "AFTER_FIRST_INSERT"
    AFTER_AGGREGATE_UPDATE = "AFTER_AGGREGATE_UPDATE"
    AFTER_TRACE_INSERT = "AFTER_TRACE_INSERT"
    AFTER_AUDIT_INSERT = "AFTER_AUDIT_INSERT"
    BEFORE_RECEIPT_FINALIZE = "BEFORE_RECEIPT_FINALIZE"
    ON_COMMIT = "ON_COMMIT"


class FaultInjectingSQLiteError(sqlite3.OperationalError):
    """Synthetic SQLite failure injected by tests."""


@dataclass(frozen=True, slots=True)
class SQLiteFaultPlan:
    """One fault injection plan."""

    stage: SQLiteFaultStage
    repeat: bool = False


class FaultInjectingSQLiteConnection:
    """Proxy connection that raises deterministic failures around SQL execution."""

    def __init__(self, connection: sqlite3.Connection, plan: SQLiteFaultPlan | None) -> None:
        self._connection = connection
        self._plan = plan
        self._has_fired = False
        self._has_seen_insert = False

    @property
    def row_factory(self) -> object:
        return self._connection.row_factory

    @property
    def in_transaction(self) -> bool:
        return self._connection.in_transaction

    def execute(self, sql: str, parameters: Any = ()) -> sqlite3.Cursor:
        normalized = " ".join(sql.strip().split()).upper()
        if self._matches(SQLiteFaultStage.BEFORE_RECEIPT_FINALIZE, normalized):
            raise FaultInjectingSQLiteError("injected sqlite fault at BEFORE_RECEIPT_FINALIZE")

        cursor = self._connection.execute(sql, parameters)

        if normalized.startswith("BEGIN IMMEDIATE"):
            self._raise_after(SQLiteFaultStage.AFTER_BEGIN)
        elif normalized.startswith("INSERT INTO"):
            if not self._has_seen_insert:
                self._has_seen_insert = True
                self._raise_after(SQLiteFaultStage.AFTER_FIRST_INSERT)
            if normalized.startswith("INSERT INTO TRACE_EVENTS"):
                self._raise_after(SQLiteFaultStage.AFTER_TRACE_INSERT)
            elif normalized.startswith("INSERT INTO AUDIT_EVENTS"):
                self._raise_after(SQLiteFaultStage.AFTER_AUDIT_INSERT)
        elif (
            normalized.startswith("UPDATE RUNS")
            or normalized.startswith("UPDATE PLANS")
            or normalized.startswith("UPDATE ACTIONS")
        ):
            self._raise_after(SQLiteFaultStage.AFTER_AGGREGATE_UPDATE)
        elif normalized.startswith("COMMIT"):
            self._raise_after(SQLiteFaultStage.ON_COMMIT)
        return cursor

    def executemany(self, sql: str, parameters: Any) -> sqlite3.Cursor:
        values = tuple(parameters)
        if not values:
            return self._connection.executemany(sql, values)
        cursor: sqlite3.Cursor | None = None
        for item in values:
            cursor = self.execute(sql, item)
        assert cursor is not None
        return cursor

    def close(self) -> None:
        self._connection.close()

    def _matches(self, stage: SQLiteFaultStage, normalized_sql: str) -> bool:
        if self._plan is None or self._plan.stage is not stage:
            return False
        if stage is SQLiteFaultStage.BEFORE_RECEIPT_FINALIZE:
            return normalized_sql.startswith("UPDATE COMMAND_RECEIPTS")
        return False

    def _raise_after(self, stage: SQLiteFaultStage) -> None:
        if self._plan is None or self._plan.stage is not stage:
            return
        if self._has_fired and not self._plan.repeat:
            return
        self._has_fired = True
        raise FaultInjectingSQLiteError(f"injected sqlite fault at {stage.value}")


class FaultInjectingSqliteUnitOfWork:
    """SQLite unit of work backed by a fault-injecting connection proxy."""

    def __init__(self, database_path: Path, plan: SQLiteFaultPlan | None) -> None:
        self._database_path = database_path
        self._plan = plan
        self._connection: FaultInjectingSQLiteConnection | None = None
        self._committed = False

    def __enter__(self) -> FaultInjectingSqliteUnitOfWork:
        raw_connection = connect_sqlite(self._database_path)
        connection = FaultInjectingSQLiteConnection(raw_connection, self._plan)
        connection.execute("BEGIN IMMEDIATE;")
        self._connection = connection
        sqlite_connection = cast(sqlite3.Connection, connection)
        self.conversations = SqliteConversationRepository(sqlite_connection)
        self.runs = SqliteRunRepository(sqlite_connection)
        self.messages = SqliteMessageRepository(sqlite_connection)
        self.command_receipts = SqliteCommandReceiptRepository(sqlite_connection)
        self.plans = SqlitePlanRepository(sqlite_connection)
        self.actions = SqliteActionRepository(sqlite_connection)
        self.resource_refs = SqliteResourceRefRepository(sqlite_connection)
        self.evidence = SqliteEvidenceRepository(sqlite_connection)
        self.approvals = SqliteApprovalRepository(sqlite_connection)
        self.execution_attempts = SqliteExecutionAttemptRepository(sqlite_connection)
        self.verifications = SqliteVerificationRepository(sqlite_connection)
        self.audits = SqliteAuditEventRepository(sqlite_connection)
        self.traces = SqliteTraceEventRepository(sqlite_connection)
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


def fault_injecting_unit_of_work_factory(
    database_path: Path,
    plan: SQLiteFaultPlan | None,
) -> Callable[[], UnitOfWork]:
    """Create a unit-of-work factory that injects SQLite faults."""

    def _factory() -> FaultInjectingSqliteUnitOfWork:
        return FaultInjectingSqliteUnitOfWork(database_path, plan)

    return cast(Callable[[], UnitOfWork], _factory)
