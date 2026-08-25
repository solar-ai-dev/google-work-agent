from __future__ import annotations

from pathlib import Path

from google_work_agent.adapters.persistence import apply_migrations, connect_sqlite
from google_work_agent.adapters.persistence.unit_of_work import sqlite_unit_of_work_factory
from google_work_agent.application.use_cases.message.list_conversation_messages import (
    ListConversationMessagesHandler,
    ListConversationMessagesQuery,
)


def test_list_conversation_messages_returns_timeline_order(tmp_path: Path) -> None:
    database_path = tmp_path / "messages.db"
    with connect_sqlite(database_path) as connection:
        apply_migrations(connection)
        connection.execute(
            """INSERT INTO google_accounts (id, email, connected_at_ms)
            VALUES ('a-1', 'a@example.com', 1)"""
        )
        connection.execute("INSERT INTO conversations VALUES ('c-1', 'a-1', 'one', 1, 1)")
        connection.execute(
            """INSERT INTO messages VALUES
            ('m-2', 'c-1', NULL, 'ASSISTANT', 'two', 20),
            ('m-1', 'c-1', NULL, 'USER', 'one', 10)"""
        )
    handler = ListConversationMessagesHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path)
    )

    result = handler(ListConversationMessagesQuery("c-1"))

    assert [item.content for item in result.items] == ["one", "two"]
    assert result.truncated is False
