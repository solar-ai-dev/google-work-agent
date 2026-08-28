"""SQLite implementation of the owner-local connected-account support surface."""

import sqlite3
from hashlib import sha256

from google_work_agent.ports.persistence.connected_account_store import ConnectedAccount


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
        self, *, email: str, display_name: str | None, connected_at_ms: int
    ) -> ConnectedAccount:
        normalized_email = email.strip().lower()
        account_id = _account_id_for_email(normalized_email)
        self._connection.execute(
            """INSERT INTO google_accounts
                   (id, email, display_name, connected_at_ms, disconnected_at_ms)
               VALUES (?, ?, ?, ?, NULL)
               ON CONFLICT(email) DO UPDATE SET
                   display_name = excluded.display_name,
                   disconnected_at_ms = NULL;""",
            (account_id, normalized_email, display_name, connected_at_ms),
        )
        current = self.get_current()
        if current is None:
            raise RuntimeError("connected Google account was not persisted")
        return current


def _account_id_for_email(email: str) -> str:
    digest = sha256(email.encode("utf-8")).hexdigest()
    return f"acct-{digest[:24]}"
