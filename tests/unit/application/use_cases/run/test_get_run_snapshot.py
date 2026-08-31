from __future__ import annotations

from pathlib import Path

from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.migration import apply_migrations
from google_work_agent.adapters.persistence.sqlite.unit_of_work import sqlite_unit_of_work_factory
from google_work_agent.application.use_cases.run.get_run_snapshot import (
    GetRunSnapshotHandler,
    GetRunSnapshotQuery,
)


def test_run_snapshot_projects_durable_terminal_kind_and_run_messages_after_restart(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "snapshot.db"
    with connect_sqlite(database_path) as connection:
        apply_migrations(connection)
        connection.execute(
            "INSERT INTO google_accounts (id, email, connected_at_ms) "
            "VALUES ('account-1', 'u@example.com', 1)"
        )
        connection.execute(
            "INSERT INTO conversations VALUES ('conversation-1', 'account-1', 'Inbox', 1, 3)"
        )
        connection.execute(
            """INSERT INTO runs (
                id, conversation_id, entry_mode, status, langgraph_thread_id,
                requested_mode, budget_json, version, started_at_ms, finished_at_ms,
                terminal_result_kind
            ) VALUES ('run-1', 'conversation-1', 'AGENT_SEARCH', 'COMPLETED',
                      'thread-1', 'AUTO', '{}', 5, 1, 3, 'SUCCESS')"""
        )
        connection.execute(
            "INSERT INTO messages VALUES "
            "('m-1', 'conversation-1', 'run-1', 'USER', 'request', 1), "
            "('m-2', 'conversation-1', 'run-1', 'ASSISTANT', 'done', 3)"
        )

    result = GetRunSnapshotHandler(unit_of_work_factory=sqlite_unit_of_work_factory(database_path))(
        GetRunSnapshotQuery("run-1")
    )

    assert result is not None
    assert result.run.run_id == "run-1"
    assert result.run.status == "COMPLETED"
    assert [item.content for item in result.messages] == ["request", "done"]
    assert result.current_plan is None
    assert result.context_preview is None
    assert result.pending_interrupt is None
    assert result.recovery is None
    assert result.error is None
    assert result.terminal_result_kind == "SUCCESS"
    assert result.projection_version == 1
