"""Regression tests for canonical conversation/message read models."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from google_work_agent.application.use_cases.conversation.get_conversation_history import GetConversationHistoryHandler, GetConversationHistoryQuery
from google_work_agent.application.use_cases.conversation.get_latest_run import GetLatestRunHandler, GetLatestRunQuery
from google_work_agent.application.use_cases.conversation.list_conversations import ListConversationsHandler, ListConversationsQuery


def _connect(path: Path):
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def _database(tmp_path: Path) -> Path:
    path = tmp_path / "conversation.db"
    with _connect(path) as connection:
        connection.executescript("""
            CREATE TABLE conversations (id TEXT PRIMARY KEY, account_id TEXT NOT NULL, title TEXT NOT NULL, created_at_ms INTEGER NOT NULL, updated_at_ms INTEGER NOT NULL);
            CREATE TABLE messages (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, run_id TEXT, role TEXT NOT NULL, content TEXT NOT NULL, created_at_ms INTEGER NOT NULL);
            CREATE TABLE runs (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, status TEXT NOT NULL, version INTEGER NOT NULL, started_at_ms INTEGER NOT NULL, finished_at_ms INTEGER);
            INSERT INTO conversations VALUES ('c-a', 'acct-a', 'A', 1, 30), ('c-b', 'acct-b', 'B', 2, 40);
            INSERT INTO messages VALUES ('m-1', 'c-a', 'r-1', 'USER', 'first', 10), ('m-2', 'c-a', 'r-1', 'ASSISTANT', 'second', 20);
            INSERT INTO runs VALUES ('r-1', 'c-a', 'COMPLETED', 4, 11, 21), ('r-2', 'c-a', 'ANALYZING', 1, 31, NULL);
        """)
    return path


def test_list_conversations_is_account_scoped(tmp_path: Path) -> None:
    path = _database(tmp_path)
    result = ListConversationsHandler(database_path=path, connection_factory=_connect)(ListConversationsQuery(account_id="acct-a", cursor=None, page_size=20))
    assert [item.id for item in result.items] == ["c-a"]


def test_history_is_stable_timeline_and_not_run_input_assembly(tmp_path: Path) -> None:
    path = _database(tmp_path)
    result = GetConversationHistoryHandler(database_path=path, connection_factory=_connect)(GetConversationHistoryQuery(conversation_id="c-a"))
    assert result is not None
    assert [item.content for item in result.messages] == ["first", "second"]
    assert [item.run_id for item in result.runs] == ["r-1", "r-2"]
    assert result.truncated is False


def test_latest_run_association_is_conversation_local(tmp_path: Path) -> None:
    path = _database(tmp_path)
    result = GetLatestRunHandler(database_path=path, connection_factory=_connect)(GetLatestRunQuery(conversation_id="c-a"))
    assert result is not None
    assert result.run_id == "r-2"
    assert result.status == "ANALYZING"
