"""Integration tests for provisioning the google_accounts identity row."""

from __future__ import annotations

from pathlib import Path

import pytest

from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.migration import apply_migrations
from google_work_agent.adapters.persistence.sqlite.connected_account_store import (
    sqlite_connected_account_store_factory,
)


def _fresh_store(tmp_path: Path):  # type: ignore[no-untyped-def]
    database_path = tmp_path / "provisioning.db"
    connection = connect_sqlite(database_path)
    try:
        apply_migrations(connection)
    finally:
        connection.close()
    return sqlite_connected_account_store_factory(database_path), database_path


def test_ensure_google__account_connected_creates__a_new_row(tmp_path: Path) -> None:
    factory, _ = _fresh_store(tmp_path)
    with factory() as store:
        store.ensure_connected(
            account_id="account-1",
            email="user@example.com",
            display_name="User Name",
            connected_at_ms=1_000,
        )
    with factory() as store:
        account = store.get_current()
    assert account is not None
    assert account.email == "user@example.com"
    assert account.display_name == "User Name"


def test_ensure_google_account__connected_is_idempotent_and__keeps_the_same_id(
    tmp_path: Path,
) -> None:
    factory, _ = _fresh_store(tmp_path)
    with factory() as store:
        first = store.ensure_connected(
            account_id="account-1",
            email="user@example.com",
            display_name="User Name",
            connected_at_ms=1_000,
        )
    assert first is not None

    with factory() as store:
        second = store.ensure_connected(
            account_id="account-1",
            email="user@example.com",
            display_name="User Name",
            connected_at_ms=2_000,
        )

    assert second is not None
    assert second.account_id == first.account_id


def test_ensure_google__account_connected_reactivates__a_disconnected_account(
    tmp_path: Path,
) -> None:
    factory, database_path = _fresh_store(tmp_path)
    with factory() as store:
        original = store.ensure_connected(
            account_id="account-1",
            email="user@example.com",
            display_name="User Name",
            connected_at_ms=1_000,
        )
    assert original is not None

    connection = connect_sqlite(database_path)
    try:
        connection.execute(
            "UPDATE google_accounts SET disconnected_at_ms = 1500 WHERE id = ?;",
            (original.account_id,),
        )
    finally:
        connection.close()
    with factory() as store:
        assert store.get_current() is None

    with factory() as store:
        reconnected = store.ensure_connected(
            account_id="account-1",
            email="user@example.com",
            display_name="User Name",
            connected_at_ms=2_000,
        )
    assert reconnected is not None
    assert reconnected.account_id == original.account_id


def test_ensure_google__account_connected__updates_display_name(tmp_path: Path) -> None:
    factory, _ = _fresh_store(tmp_path)
    with factory() as store:
        store.ensure_connected(
            account_id="account-1",
            email="user@example.com",
            display_name="Old Name",
            connected_at_ms=1_000,
        )
        store.ensure_connected(
            account_id="account-1",
            email="user@example.com",
            display_name="New Name",
            connected_at_ms=2_000,
        )
        account = store.get_current()
    assert account is not None
    assert account.display_name == "New Name"


def test_connecting_another__account_deactivates_the__previous_current_account(
    tmp_path: Path,
) -> None:
    factory, database_path = _fresh_store(tmp_path)
    with factory() as store:
        first = store.ensure_connected(
            account_id="account-1",
            email="first@example.com",
            display_name="First",
            connected_at_ms=1_000,
        )
        second = store.ensure_connected(
            account_id="account-2",
            email="second@example.com",
            display_name="Second",
            connected_at_ms=2_000,
        )
    with connect_sqlite(database_path) as connection:
        rows = connection.execute(
            "SELECT id, disconnected_at_ms FROM google_accounts ORDER BY connected_at_ms;"
        ).fetchall()
    assert rows[0]["id"] == first.account_id and rows[0]["disconnected_at_ms"] == 2_000
    assert rows[1]["id"] == second.account_id and rows[1]["disconnected_at_ms"] is None


def test_disconnect_is_idempotent__and_db_rejects__a_second_active_account(
    tmp_path: Path,
) -> None:
    factory, database_path = _fresh_store(tmp_path)
    with factory() as store:
        account = store.ensure_connected(
            account_id="account-1",
            email="user@example.com",
            display_name="User",
            connected_at_ms=1_000,
        )
    with factory() as store:
        assert store.disconnect(account_id=account.account_id, disconnected_at_ms=2_000)
        assert store.disconnect(account_id=account.account_id, disconnected_at_ms=3_000)
    with connect_sqlite(database_path) as connection:
        connection.execute(
            "INSERT INTO google_accounts VALUES ('active-1', 'a@example.com', NULL, 4, NULL);"
        )
        with pytest.raises(Exception, match="uq_google_accounts_one_active"):
            connection.execute(
                "INSERT INTO google_accounts VALUES ('active-2', 'b@example.com', NULL, 5, NULL);"
            )
