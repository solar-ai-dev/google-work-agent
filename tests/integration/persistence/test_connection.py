import sqlite3
from pathlib import Path

from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.migration import apply_migrations
from google_work_agent.adapters.persistence.sqlite.unit_of_work import (
    sqlite_read_unit_of_work_factory,
    sqlite_unit_of_work_factory,
)


def test_file_database_connection_applies_required_pragmas(tmp_path: Path) -> None:
    database_path = tmp_path / "connection.db"

    connection = connect_sqlite(database_path)
    try:
        assert connection.execute("PRAGMA foreign_keys;").fetchone()[0] == 1
        assert connection.execute("PRAGMA journal_mode;").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA synchronous;").fetchone()[0] == 2
        assert connection.execute("PRAGMA busy_timeout;").fetchone()[0] == 5000

        connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, name TEXT NOT NULL);")
        connection.execute("INSERT INTO sample (name) VALUES (?);", ("agent",))
        row = connection.execute("SELECT id, name FROM sample;").fetchone()

        assert isinstance(row, sqlite3.Row)
        assert row["name"] == "agent"
    finally:
        connection.close()

    assert database_path.exists()


def test_connection_close_is_caller_controlled(tmp_path: Path) -> None:
    connection = connect_sqlite(tmp_path / "close.db")
    connection.close()

    try:
        connection.execute("SELECT 1;")
    except sqlite3.ProgrammingError as exc:
        assert "closed" in str(exc)
    else:
        raise AssertionError("closed SQLite connection accepted a query")


def test_read_unit_of_work_does_not_compete_for_writer_lock(tmp_path: Path) -> None:
    database_path = tmp_path / "read-uow.db"
    with connect_sqlite(database_path) as connection:
        apply_migrations(connection, now_ms=lambda: 1)
    with sqlite_unit_of_work_factory(database_path)() as unit_of_work:
        unit_of_work.commit()

    writer = connect_sqlite(database_path)
    try:
        writer.execute("BEGIN IMMEDIATE;")
        with sqlite_read_unit_of_work_factory(database_path)() as unit_of_work:
            assert unit_of_work.runs.get("missing-run") is None
    finally:
        if writer.in_transaction:
            writer.execute("ROLLBACK;")
        writer.close()
