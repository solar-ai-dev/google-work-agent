import sqlite3
from json import loads

from google_work_agent.adapters.persistence.sqlite.repositories.trace_event_repository import (
    SqliteTraceEventRepository,
)
from google_work_agent.domain.trace_event.model import TraceEvent


def test_trace_event__repository_sanitizes__lists_and_purges() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """CREATE TABLE trace_events (
            id INTEGER PRIMARY KEY, run_id TEXT, action_id TEXT, event_type TEXT,
            status TEXT, duration_ms INTEGER, payload_json TEXT, created_at_ms INTEGER
        )"""
    )
    repository = SqliteTraceEventRepository(connection)
    repository.append(
        TraceEvent(
            "run-1",
            None,
            "TEST",
            "OK",
            1,
            '{"access_token":"access_abcdefghijklmnopqrstuvwxyz0123456789"}',
            1,
        )
    )

    page = repository.list_page(None, 10)
    assert len(page) == 1
    assert "access_abcdefghijklmnopqrstuvwxyz0123456789" not in page[0].payload_json
    assert loads(page[0].payload_json)["schema_version"] == 1
    assert repository.purge_before(2) == 1
