from __future__ import annotations

from pathlib import Path

from google_work_agent.adapters.persistence import apply_migrations, connect_sqlite
from google_work_agent.adapters.persistence.sqlite.unit_of_work import sqlite_unit_of_work_factory
from google_work_agent.application.use_cases.conversation.get_conversation_history import (
    GetConversationHistoryHandler,
    GetConversationHistoryQuery,
)


def test_history_is_a_bounded_timeline_projection(tmp_path: Path) -> None:
    database_path = tmp_path / "history.db"
    with connect_sqlite(database_path) as connection:
        apply_migrations(connection)
        connection.execute(
            """INSERT INTO google_accounts (id, email, connected_at_ms)
            VALUES ('a-1', 'a@example.com', 1)"""
        )
        connection.execute("INSERT INTO conversations VALUES ('c-1', 'a-1', 'one', 1, 20)")
        connection.execute(
            """INSERT INTO messages VALUES
            ('m-1', 'c-1', NULL, 'USER', 'one', 10),
            ('m-2', 'c-1', NULL, 'ASSISTANT', 'two', 20)"""
        )
    handler = GetConversationHistoryHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        database_path=database_path,
        connection_factory=connect_sqlite,
    )

    result = handler(GetConversationHistoryQuery("c-1"))

    assert result is not None
    assert [item.content for item in result.messages] == ["one", "two"]
    assert result.runs == ()
    assert result.truncated is False
