"""Fault-injecting SQLite wrappers for transactional tests."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, cast

from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.repositories import (
    SQLiteAuditRepository,
    SQLiteCommandReceiptRepository,
    SQLiteConversationRepository,
    SQLiteMessageRepository,
    SQLiteRunRepository,
    SQLiteTraceRepository,
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
        elif normalized.startswith("UPDATE RUNS"):
            self._raise_after(SQLiteFaultStage.AFTER_AGGREGATE_UPDATE)
        elif normalized.startswith("COMMIT"):
            self._raise_after(SQLiteFaultStage.ON_COMMIT)
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


class FaultInjectingSQLiteUnitOfWork:
    """SQLite unit of work backed by a fault-injecting connection proxy."""

    def __init__(self, database_path: Path, plan: SQLiteFaultPlan | None) -> None:
        self._database_path = database_path
        self._plan = plan
        self._connection: FaultInjectingSQLiteConnection | None = None
        self._committed = False

    def __enter__(self) -> FaultInjectingSQLiteUnitOfWork:
        raw_connection = connect_sqlite(self._database_path)
        connection = FaultInjectingSQLiteConnection(raw_connection, self._plan)
        connection.execute("BEGIN IMMEDIATE;")
        self._connection = connection
        sqlite_connection = cast(sqlite3.Connection, connection)
        self.conversations = SQLiteConversationRepository(sqlite_connection)
        self.runs = SQLiteRunRepository(sqlite_connection)
        self.messages = SQLiteMessageRepository(sqlite_connection)
        self.command_receipts = SQLiteCommandReceiptRepository(sqlite_connection)
        self.audits = SQLiteAuditRepository(sqlite_connection)
        self.traces = SQLiteTraceRepository(sqlite_connection)
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

    def _factory() -> FaultInjectingSQLiteUnitOfWork:
        return FaultInjectingSQLiteUnitOfWork(database_path, plan)

    return cast(Callable[[], UnitOfWork], _factory)
