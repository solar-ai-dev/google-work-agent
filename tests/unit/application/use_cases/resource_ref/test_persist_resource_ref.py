from pathlib import Path

from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.migration import apply_migrations
from google_work_agent.adapters.persistence.sqlite.unit_of_work import sqlite_unit_of_work_factory
from google_work_agent.application.use_cases.resource_ref.persist_resource_ref import (
    PersistResourceRefCommand,
    PersistResourceRefHandler,
)
from google_work_agent.domain.resource_ref.model import ResourceRef as ResourceRefRecord


def test_persists_connector_bound_resource_ref(tmp_path: Path) -> None:
    path = tmp_path / "persist.db"
    with connect_sqlite(path) as connection:
        apply_migrations(connection)
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
    record = ResourceRefRecord(
        id="ref-1",
        run_id="run-1",
        connector_id="google_workspace",
        resource_type="task",
        resource_id="task-1",
        parent_resource_id="list-1",
        canonical_url=None,
        title="Task",
        event_time_ms=None,
        version_token="v1",
        metadata_json="{}",
        captured_at_ms=1,
    )

    result = PersistResourceRefHandler(unit_of_work_factory=sqlite_unit_of_work_factory(path))(
        PersistResourceRefCommand(record)
    )

    assert result.resource_ref == record
