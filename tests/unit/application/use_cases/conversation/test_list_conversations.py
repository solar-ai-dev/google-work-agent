from __future__ import annotations

from pathlib import Path

from google_work_agent.adapters.persistence import apply_migrations, connect_sqlite
from google_work_agent.adapters.persistence.unit_of_work import sqlite_unit_of_work_factory
from google_work_agent.application.use_cases.conversation.list_conversations import (
    ListConversationsHandler,
    ListConversationsQuery,
)


def test_list_conversations_is_account_scoped(tmp_path: Path) -> None:
    database_path = tmp_path / "list.db"
    with connect_sqlite(database_path) as connection:
        apply_migrations(connection)
        connection.execute(
            """INSERT INTO google_accounts (id, email, connected_at_ms) VALUES
            ('a-1', 'a@example.com', 1), ('a-2', 'b@example.com', 1)"""
        )
        connection.execute(
            """INSERT INTO conversations VALUES
            ('c-1', 'a-1', 'one', 1, 10), ('c-2', 'a-2', 'two', 1, 20)"""
        )
    handler = ListConversationsHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path)
    )

    result = handler(ListConversationsQuery("a-1", None, 20))

    assert [item.id for item in result.items] == ["c-1"]
