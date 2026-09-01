"""Current connector/resource registry persistence constraints."""

import sqlite3
from pathlib import Path

import pytest

from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.migration import apply_migrations


def test_current_registry_rejects_unregistered_connector_resource_identity(tmp_path: Path) -> None:
    connection = connect_sqlite(tmp_path / "connector-registry.db")
    try:
        apply_migrations(connection, now_ms=lambda: 1)
        connection.execute(
            "INSERT INTO google_accounts VALUES ('account-1', 'u@example.com', NULL, 1, NULL);"
        )
        connection.execute(
            "INSERT INTO conversations VALUES ('conversation-1', 'account-1', 'Test', 1, 1);"
        )
        connection.execute(
            """
            INSERT INTO runs (
                id, conversation_id, entry_mode, status, langgraph_thread_id,
                requested_mode, budget_json, version, started_at_ms
            ) VALUES ('run-1', 'conversation-1', 'AGENT_SEARCH', 'PLANNING',
                      'thread-1', 'AUTO', '{}', 0, 1);
            """
        )
        connection.execute(
            """
            INSERT INTO resource_refs (
                id, run_id, connector_id, resource_type, resource_id,
                metadata_json, captured_at_ms
            ) VALUES ('resource-google', 'run-1', 'google_workspace', 'task',
                      'shared-task-id', '{}', 1);
            """
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """INSERT INTO resource_refs (
                       id, run_id, connector_id, resource_type, resource_id,
                       metadata_json, captured_at_ms
                   ) VALUES ('resource-github', 'run-1', 'github', 'task',
                             'shared-task-id', '{}', 1);"""
            )
        rows = connection.execute(
            """SELECT connector_id, resource_type, resource_id
               FROM resource_refs WHERE run_id='run-1' AND resource_id='shared-task-id';"""
        ).fetchall()
        assert [tuple(row) for row in rows] == [("google_workspace", "task", "shared-task-id")]
    finally:
        connection.close()
