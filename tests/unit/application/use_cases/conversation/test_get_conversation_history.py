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
    )

    result = handler(GetConversationHistoryQuery("c-1"))

    assert result is not None
    assert [item.content for item in result.messages] == ["one", "two"]
    assert result.runs == ()
    assert result.truncated is False


def test_history_bounds_messages_and_runs_independently(tmp_path: Path) -> None:
    database_path = tmp_path / "independent-history.db"
    with connect_sqlite(database_path) as connection:
        apply_migrations(connection)
        connection.execute(
            "INSERT INTO google_accounts (id, email, connected_at_ms) "
            "VALUES ('a-1', 'a@example.com', 1)"
        )
        connection.execute("INSERT INTO conversations VALUES ('c-1', 'a-1', 'one', 1, 20)")
        for index in range(1, 5):
            connection.execute(
                """INSERT INTO runs (
                    id, conversation_id, entry_mode, status, langgraph_thread_id,
                    requested_mode, budget_json, version, started_at_ms, finished_at_ms
                ) VALUES (?, 'c-1', 'AGENT_SEARCH', 'COMPLETED', ?,
                          'AUTO', '{}', 0, ?, ?)""",
                (f"r-{index}", f"t-{index}", index * 10, index * 10 + 1),
            )
        connection.execute(
            "INSERT INTO messages VALUES "
            "('m-1', 'c-1', 'r-1', 'USER', 'old', 10), "
            "('m-4', 'c-1', 'r-4', 'USER', 'new', 40)"
        )
    handler = GetConversationHistoryHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        history_message_limit=1,
        history_run_limit=3,
    )

    result = handler(GetConversationHistoryQuery("c-1"))

    assert result is not None
    assert [item.content for item in result.messages] == ["new"]
    assert [item.run_id for item in result.runs] == ["r-2", "r-3", "r-4"]
    assert result.truncated is True
