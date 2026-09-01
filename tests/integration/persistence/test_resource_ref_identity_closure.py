"""Current connector-qualified resource identity behavior."""

import sqlite3
from pathlib import Path

import pytest

from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.migration import apply_migrations
from google_work_agent.adapters.persistence.sqlite.repositories.resource_ref_repository import (
    SqliteResourceRefRepository,
)
from google_work_agent.domain.resource_ref.model import ResourceRef as ResourceRefRecord


def test_same_external_id_coexists_across_registered_resource_types(tmp_path: Path) -> None:
    connection = connect_sqlite(tmp_path / "resource-identity.db")
    try:
        apply_migrations(connection, now_ms=lambda: 1)
        _seed_run(connection)
        repository = SqliteResourceRefRepository(connection)
        repository.upsert_bound_ref(_resource_ref("resource-a", "calendar_event", title="A"))
        repository.upsert_bound_ref(_resource_ref("resource-b", "gmail_message", title="B"))

        rows = connection.execute(
            """SELECT connector_id, resource_type, resource_id, title
               FROM resource_refs
               WHERE run_id='run-1' AND resource_id='external-X'
               ORDER BY resource_type;"""
        ).fetchall()
        assert [tuple(row) for row in rows] == [
            ("google_workspace", "calendar_event", "external-X", "A"),
            ("google_workspace", "gmail_message", "external-X", "B"),
        ]

        repository.upsert_bound_ref(_resource_ref("replacement-id", "calendar_event", title="A2"))
        rows = connection.execute(
            """SELECT id, connector_id, title FROM resource_refs
               WHERE run_id='run-1' AND resource_id='external-X'
               ORDER BY resource_type;"""
        ).fetchall()
        assert [tuple(row) for row in rows] == [
            ("resource-a", "google_workspace", "A2"),
            ("resource-b", "google_workspace", "B"),
        ]
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """INSERT INTO resource_refs (
                       id, run_id, connector_id, resource_type, resource_id,
                       metadata_json, captured_at_ms
                   ) VALUES ('duplicate', 'run-1', 'google_workspace', 'calendar_event',
                             'external-X', '{}', 2);"""
            )
    finally:
        connection.close()


def _resource_ref(record_id: str, resource_type: str, *, title: str) -> ResourceRefRecord:
    return ResourceRefRecord(
        id=record_id,
        run_id="run-1",
        connector_id="google_workspace",
        resource_type=resource_type,
        resource_id="external-X",
        parent_resource_id=None,
        canonical_url=None,
        title=title,
        event_time_ms=None,
        version_token="v1",
        metadata_json="{}",
        captured_at_ms=1,
    )


def _seed_run(connection: sqlite3.Connection) -> None:
    connection.execute(
        "INSERT INTO google_accounts VALUES ('account-1', 'u@example.com', NULL, 1, NULL);"
    )
    connection.execute(
        "INSERT INTO conversations VALUES ('conversation-1', 'account-1', 'Test', 1, 1);"
    )
    connection.execute(
        """INSERT INTO runs (
               id, conversation_id, entry_mode, status, langgraph_thread_id,
               requested_mode, budget_json, version, started_at_ms
           ) VALUES ('run-1', 'conversation-1', 'AGENT_SEARCH', 'PLANNING',
                     'thread-1', 'AUTO', '{}', 0, 1);"""
    )
    connection.commit()
