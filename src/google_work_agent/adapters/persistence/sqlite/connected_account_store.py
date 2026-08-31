"""SQLite implementation of the owner-local connected-account support surface."""

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path

from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.ports.connector.connected_account_store import (
    ConnectedAccount,
    ConnectedAccountStore,
)


class SqliteConnectedAccountStore:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get_current(self) -> ConnectedAccount | None:
        row = self._connection.execute(
            """SELECT id, email, display_name
               FROM google_accounts
               WHERE disconnected_at_ms IS NULL
               ORDER BY connected_at_ms DESC, id DESC
               LIMIT 1;"""
        ).fetchone()
        if row is None:
            return None
        return ConnectedAccount(
            account_id=str(row["id"]),
            email=str(row["email"]),
            display_name=None if row["display_name"] is None else str(row["display_name"]),
        )

    def ensure_connected(
        self,
        *,
        account_id: str,
        email: str,
        display_name: str | None,
        connected_at_ms: int,
    ) -> ConnectedAccount:
        normalized_email = email.strip().lower()
        if not account_id:
            raise ValueError("connector account_id is required")
        self._connection.execute(
            """UPDATE google_accounts
               SET disconnected_at_ms = MAX(connected_at_ms, ?)
               WHERE disconnected_at_ms IS NULL AND id <> ?;""",
            (connected_at_ms, account_id),
        )
        self._connection.execute(
            """INSERT INTO google_accounts
                   (id, email, display_name, connected_at_ms, disconnected_at_ms)
               VALUES (?, ?, ?, ?, NULL)
               ON CONFLICT(email) DO UPDATE SET
                   display_name = excluded.display_name,
                   connected_at_ms = excluded.connected_at_ms,
                   disconnected_at_ms = NULL;""",
            (account_id, normalized_email, display_name, connected_at_ms),
        )
        current = self.get_current()
        if current is None:
            raise RuntimeError("connected Google account was not persisted")
        return current

    def disconnect(self, *, account_id: str, disconnected_at_ms: int) -> bool:
        cursor = self._connection.execute(
            """UPDATE google_accounts
               SET disconnected_at_ms = MAX(connected_at_ms, ?)
               WHERE id = ? AND disconnected_at_ms IS NULL;""",
            (disconnected_at_ms, account_id),
        )
        if cursor.rowcount == 1:
            return True
        row = self._connection.execute(
            "SELECT disconnected_at_ms FROM google_accounts WHERE id=?;",
            (account_id,),
        ).fetchone()
        return row is not None and row["disconnected_at_ms"] is not None


def sqlite_connected_account_store_factory(
    database_path: Path,
) -> Callable[[], AbstractContextManager[ConnectedAccountStore]]:
    @contextmanager
    def _factory() -> Iterator[ConnectedAccountStore]:
        with connect_sqlite(database_path) as connection:
            connection.execute("BEGIN IMMEDIATE;")
            try:
                yield SqliteConnectedAccountStore(connection)
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    return _factory
