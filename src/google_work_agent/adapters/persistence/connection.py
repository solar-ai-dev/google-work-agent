"""SQLite connection factory for the domain store."""

import sqlite3
from pathlib import Path

_BUSY_TIMEOUT_MS = 5000
_TIMEOUT_SECONDS = _BUSY_TIMEOUT_MS / 1000


def connect_sqlite(database_path: Path) -> sqlite3.Connection:
    """Open a SQLite connection with the product-required PRAGMA settings.

    The caller owns the returned connection and is responsible for closing it.
    Parent directories are not created implicitly.
    """
    connection = sqlite3.connect(
        str(database_path),
        timeout=_TIMEOUT_SECONDS,
        isolation_level=None,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    connection.execute("PRAGMA journal_mode = WAL;")
    connection.execute("PRAGMA synchronous = FULL;")
    connection.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS};")
    return connection
