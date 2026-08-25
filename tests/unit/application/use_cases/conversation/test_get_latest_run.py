from __future__ import annotations

import sqlite3
from pathlib import Path

from google_work_agent.application.use_cases.conversation.get_latest_run import (
    GetLatestRunHandler,
    GetLatestRunQuery,
)


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def test_latest_run_association_is_conversation_local(tmp_path: Path) -> None:
    database_path = tmp_path / "latest.db"
    with _connect(database_path) as connection:
        connection.execute(
            """CREATE TABLE runs (
                id TEXT PRIMARY KEY, conversation_id TEXT, status TEXT,
                version INTEGER, started_at_ms INTEGER
            )"""
        )
        connection.execute("INSERT INTO runs VALUES ('r-1', 'c-1', 'COMPLETED', 1, 10)")
        connection.execute("INSERT INTO runs VALUES ('r-2', 'c-1', 'ANALYZING', 2, 20)")
    handler = GetLatestRunHandler(database_path=database_path, connection_factory=_connect)

    result = handler(GetLatestRunQuery("c-1"))

    assert result is not None
    assert result.run_id == "r-2"
