import sqlite3
from json import loads

from google_work_agent.adapters.persistence.sqlite.repositories.audit_event_repository import (
    SqliteAuditEventRepository,
)
from google_work_agent.domain.audit_event.model import AuditEvent


def test_audit_event_repository_sanitizes_lists_and_purges() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """CREATE TABLE audit_events (
            id INTEGER PRIMARY KEY, account_id TEXT, run_id TEXT, action_id TEXT,
            actor_type TEXT, actor_id TEXT, actor_display TEXT, event_type TEXT,
            outcome TEXT, metadata_json TEXT, created_at_ms INTEGER
        )"""
    )
    repository = SqliteAuditEventRepository(connection)
    repository.append(
        AuditEvent(
            None,
            "run-1",
            None,
            "SYSTEM",
            "system",
            None,
            "TEST",
            "OK",
            '{"access_token":"access_abcdefghijklmnopqrstuvwxyz0123456789"}',
            1,
        )
    )

    page = repository.list_page(None, 10)
    assert len(page) == 1
    assert "access_abcdefghijklmnopqrstuvwxyz0123456789" not in page[0].metadata_json
    assert loads(page[0].metadata_json)["schema_version"] == 1
    assert repository.purge_before(2) == 1
