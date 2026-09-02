import sqlite3
from pathlib import Path

from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.migration import apply_migrations
from google_work_agent.adapters.persistence.sqlite.repositories.resource_ref_repository import (
    SqliteResourceRefRepository,
)
from google_work_agent.domain.resource_ref.model import ResourceRef as ResourceRefRecord


def test_upsert_uses_connector__aware_identity_and__returns_existing_server_id(
    tmp_path: Path,
) -> None:
    connection = _database(tmp_path)
    try:
        repository = SqliteResourceRefRepository(connection)
        first = repository.upsert_bound_ref(_record("ref-1", title="one"))
        updated = repository.upsert_bound_ref(_record("ignored-new-id", title="two"))

        assert first.id == "ref-1"
        assert updated.id == "ref-1"
        assert updated.title == "two"
        assert repository.get("ref-1") == updated
        assert repository.list_for_run_bounded("run-1", limit=10) == (updated,)
    finally:
        connection.close()


def _database(tmp_path: Path) -> sqlite3.Connection:
    connection = connect_sqlite(tmp_path / "resource-ref.db")
    apply_migrations(connection, now_ms=lambda: 1)
    connection.execute(
        "INSERT INTO google_accounts VALUES ('a-1', 'u@example.com', NULL, 1, NULL);"
    )
    connection.execute("INSERT INTO conversations VALUES ('c-1', 'a-1', 'Test', 1, 1);")
    connection.execute(
        """
        INSERT INTO runs VALUES (
            'run-1', 'c-1', 'AGENT_SEARCH', 'CREATED', 't-1',
            'AUTO', NULL, '{}', 0, 1, NULL, NULL
        );
        """
    )
    connection.commit()
    return connection


def _record(record_id: str, *, title: str) -> ResourceRefRecord:
    return ResourceRefRecord(
        id=record_id,
        run_id="run-1",
        connector_id="google_workspace",
        resource_type="task",
        resource_id="task-1",
        parent_resource_id="list-1",
        canonical_url=None,
        title=title,
        event_time_ms=None,
        version_token="v1",
        metadata_json="{}",
        captured_at_ms=1,
    )
