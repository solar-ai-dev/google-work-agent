from pathlib import Path

from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.migration import apply_migrations
from google_work_agent.adapters.persistence.sqlite.unit_of_work import sqlite_unit_of_work_factory
from google_work_agent.application.use_cases.resource_ref.resolve_resource_ref import (
    ResolveResourceRefHandler,
    ResolveResourceRefQuery,
)


def test_returns_none__for_unknown__resource_ref(tmp_path: Path) -> None:
    path = tmp_path / "resolve.db"
    with connect_sqlite(path) as connection:
        apply_migrations(connection)
    result = ResolveResourceRefHandler(unit_of_work_factory=sqlite_unit_of_work_factory(path))(
        ResolveResourceRefQuery("missing")
    )
    assert result.resource_ref is None
