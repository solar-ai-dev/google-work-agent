"""Read-model query connection boundary."""

from __future__ import annotations

from pathlib import Path
from sqlite3 import Connection
from typing import Protocol


class QueryConnectionFactory(Protocol):
    """Open one configured connection for read-model queries."""

    def __call__(self, database_path: Path) -> Connection: ...
