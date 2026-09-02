import sqlite3

from google_work_agent.adapters.persistence.sqlite.connected_account_store import (
    SqliteConnectedAccountStore,
)


def test_connected_account__store_reuses_email__identity_and_reactivates() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """CREATE TABLE google_accounts (
            id TEXT PRIMARY KEY, email TEXT UNIQUE COLLATE NOCASE,
            display_name TEXT, connected_at_ms INTEGER, disconnected_at_ms INTEGER
        )"""
    )
    store = SqliteConnectedAccountStore(connection)

    first = store.ensure_connected(
        account_id="provider-account-1",
        email="User@Example.com",
        display_name="First",
        connected_at_ms=1,
    )
    connection.execute(
        "UPDATE google_accounts SET disconnected_at_ms=2 WHERE id=?", (first.account_id,)
    )
    second = store.ensure_connected(
        account_id="provider-account-1",
        email="user@example.com",
        display_name="Second",
        connected_at_ms=3,
    )

    assert second.account_id == first.account_id
    assert second.email == "user@example.com"
    assert second.display_name == "Second"
