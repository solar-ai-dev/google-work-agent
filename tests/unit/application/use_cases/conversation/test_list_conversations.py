from __future__ import annotations

from pathlib import Path

from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.migration import apply_migrations
from google_work_agent.adapters.persistence.sqlite.unit_of_work import sqlite_unit_of_work_factory
from google_work_agent.application.use_cases.conversation.list_conversations import (
    ListConversationsHandler,
    ListConversationsQuery,
)


def test_list_conversations_is_account_scoped(tmp_path: Path) -> None:
    database_path = tmp_path / "list.db"
    with connect_sqlite(database_path) as connection:
        apply_migrations(connection)
        connection.execute(
            """INSERT INTO google_accounts (
                   id, email, connected_at_ms, disconnected_at_ms
               ) VALUES
               ('a-1', 'a@example.com', 1, NULL),
               ('a-2', 'b@example.com', 1, 2)"""
        )
        connection.execute(
            """INSERT INTO conversations VALUES
            ('c-1', 'a-1', 'one', 1, 10), ('c-2', 'a-2', 'two', 1, 20)"""
        )
    handler = ListConversationsHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path)
    )

    result = handler(ListConversationsQuery("a-1", None, 20))

    assert [item.conversation_id for item in result.items] == ["c-1"]
    assert result.items[0].schema_version == 1


def test_list_conversations_searches_title_and_message_and_projects_latest_open_run(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "search.db"
    with connect_sqlite(database_path) as connection:
        apply_migrations(connection)
        connection.execute(
            "INSERT INTO google_accounts (id, email, connected_at_ms) "
            "VALUES ('a-1', 'a@example.com', 1)"
        )
        connection.execute(
            "INSERT INTO conversations VALUES "
            "('c-1', 'a-1', 'Quarterly plan', 1, 30), "
            "('c-2', 'a-1', 'Inbox', 1, 20), "
            "('c-3', 'a-1', 'Other', 1, 10)"
        )
        connection.execute(
            "INSERT INTO messages VALUES "
            "('m-1', 'c-2', NULL, 'USER', 'quarterly evidence', 25), "
            "('m-2', 'c-2', NULL, 'ASSISTANT', 'latest', 26)"
        )
        connection.execute(
            """INSERT INTO runs (
                id, conversation_id, entry_mode, status, langgraph_thread_id,
                requested_mode, budget_json, version, started_at_ms
            ) VALUES ('r-1', 'c-2', 'AGENT_SEARCH', 'PLANNING', 't-1',
                      'AUTO', '{}', 0, 27)"""
        )
    handler = ListConversationsHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path)
    )

    result = handler(ListConversationsQuery("a-1", search=" quarterly "))

    assert [item.conversation_id for item in result.items] == ["c-1", "c-2"]
    assert result.items[1].latest_message_at_ms == 26
    assert result.items[1].open_run_id == "r-1"


def test_list_conversations_rejects_noncanonical_bounds(tmp_path: Path) -> None:
    handler = ListConversationsHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(tmp_path / "unused.db")
    )

    for page_size in (0, 51):
        try:
            handler(ListConversationsQuery("a-1", page_size=page_size))
        except ValueError:
            pass
        else:
            raise AssertionError("noncanonical page size was accepted")
