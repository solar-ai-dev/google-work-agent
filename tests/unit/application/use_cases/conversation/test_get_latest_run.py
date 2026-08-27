from __future__ import annotations

from pathlib import Path

from google_work_agent.adapters.persistence import apply_migrations, connect_sqlite
from google_work_agent.adapters.persistence.sqlite.unit_of_work import sqlite_unit_of_work_factory
from google_work_agent.application.use_cases.conversation.get_latest_run import (
    GetLatestRunHandler,
    GetLatestRunQuery,
)


def test_latest_run_association_is_conversation_local(tmp_path: Path) -> None:
    database_path = tmp_path / "latest.db"
    with connect_sqlite(database_path) as connection:
        apply_migrations(connection)
        connection.execute(
            "INSERT INTO google_accounts (id, email, connected_at_ms) "
            "VALUES ('account-1', 'account@example.com', 1)"
        )
        connection.execute("INSERT INTO conversations VALUES ('c-1', 'account-1', 'test', 1, 1)")
        connection.execute(
            """INSERT INTO runs
            (id, conversation_id, entry_mode, status, langgraph_thread_id, requested_mode,
             actual_runtime, budget_json, version, started_at_ms, finished_at_ms)
            VALUES ('r-1', 'c-1', 'AGENT_SEARCH', 'COMPLETED', 'thread-1', 'AUTO',
                    NULL, '{}', 1, 10, 11)"""
        )
        connection.execute(
            """INSERT INTO runs
            (id, conversation_id, entry_mode, status, langgraph_thread_id, requested_mode,
             actual_runtime, budget_json, version, started_at_ms, finished_at_ms)
            VALUES ('r-2', 'c-1', 'AGENT_SEARCH', 'ANALYZING', 'thread-2', 'AUTO',
                    NULL, '{}', 2, 20, NULL)"""
        )
    handler = GetLatestRunHandler(unit_of_work_factory=sqlite_unit_of_work_factory(database_path))

    result = handler(GetLatestRunQuery("c-1"))

    assert result is not None
    assert result.run_id == "r-2"
