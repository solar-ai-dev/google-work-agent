"""Integration tests for provisioning the google_accounts identity row."""

from __future__ import annotations

from pathlib import Path

from google_work_agent.adapters.persistence import apply_migrations, connect_sqlite
from google_work_agent.application.queries import QueryService


def _fresh_query_service(tmp_path: Path) -> tuple[QueryService, Path]:
    database_path = tmp_path / "provisioning.db"
    connection = connect_sqlite(database_path)
    try:
        apply_migrations(connection)
    finally:
        connection.close()
    return (
        QueryService(
            database_path=database_path,
            connection_factory=connect_sqlite,
            runtime_status_provider=_UnusedRuntimeStatusProvider(),
        ),
        database_path,
    )


class _UnusedRuntimeStatusProvider:
    def get_summary(self) -> object:
        raise NotImplementedError


def test_ensure_google_account_connected_creates_a_new_row(tmp_path: Path) -> None:
    query_service, _ = _fresh_query_service(tmp_path)

    query_service.ensure_google_account_connected(
        email="user@example.com", display_name="User Name", now_ms=1_000
    )

    account = query_service.get_current_google_account()
    assert account is not None
    assert account.email == "user@example.com"
    assert account.display_name == "User Name"


def test_ensure_google_account_connected_is_idempotent_and_keeps_the_same_id(
    tmp_path: Path,
) -> None:
    query_service, _ = _fresh_query_service(tmp_path)

    query_service.ensure_google_account_connected(
        email="user@example.com", display_name="User Name", now_ms=1_000
    )
    first = query_service.get_current_google_account()
    assert first is not None

    query_service.ensure_google_account_connected(
        email="user@example.com", display_name="User Name", now_ms=2_000
    )
    second = query_service.get_current_google_account()

    assert second is not None
    assert second.account_id == first.account_id


def test_ensure_google_account_connected_reactivates_a_disconnected_account(
    tmp_path: Path,
) -> None:
    query_service, database_path = _fresh_query_service(tmp_path)
    query_service.ensure_google_account_connected(
        email="user@example.com", display_name="User Name", now_ms=1_000
    )
    original = query_service.get_current_google_account()
    assert original is not None

    connection = connect_sqlite(database_path)
    try:
        connection.execute(
            "UPDATE google_accounts SET disconnected_at_ms = 1500 WHERE id = ?;",
            (original.account_id,),
        )
    finally:
        connection.close()
    assert query_service.get_current_google_account() is None

    query_service.ensure_google_account_connected(
        email="user@example.com", display_name="User Name", now_ms=2_000
    )

    reconnected = query_service.get_current_google_account()
    assert reconnected is not None
    assert reconnected.account_id == original.account_id


def test_ensure_google_account_connected_updates_display_name(tmp_path: Path) -> None:
    query_service, _ = _fresh_query_service(tmp_path)
    query_service.ensure_google_account_connected(
        email="user@example.com", display_name="Old Name", now_ms=1_000
    )

    query_service.ensure_google_account_connected(
        email="user@example.com", display_name="New Name", now_ms=2_000
    )

    account = query_service.get_current_google_account()
    assert account is not None
    assert account.display_name == "New Name"
