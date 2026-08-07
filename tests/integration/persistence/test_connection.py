import sqlite3
from pathlib import Path

from google_work_agent.adapters.persistence import connect_sqlite


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
