"""Post-commit trace persistence adapter for diagnostic isolation."""

import logging
import sqlite3

from google_work_agent.adapters.persistence.sqlite.repositories.trace_event_repository import (
    SqliteTraceEventRepository,
)
from google_work_agent.domain.trace_event.model import TraceEvent
from google_work_agent.ports.persistence.trace_event_repository import (
    PersistedTraceEventRecord,
    TraceEventCursor,
)

_LOGGER = logging.getLogger(__name__)


class PostCommitTraceEventRepository:
    """Buffer traces until the owning Domain transaction commits."""

    def __init__(
        self, connection: sqlite3.Connection, *,
        environment: str = "test", release_version: str = "dev",
    ) -> None:
        self._connection = connection
        self._repository = SqliteTraceEventRepository(
            connection, environment=environment, release_version=release_version,
        )
        self._pending: list[TraceEvent] = []

    def append(self, event: TraceEvent) -> None:
        self._pending.append(event)

    def list_page(
        self, cursor: TraceEventCursor | None, limit: int
    ) -> tuple[PersistedTraceEventRecord, ...]:
        return self._repository.list_page(cursor, limit)

    def purge_before(self, timestamp_ms: int) -> int:
        return self._repository.purge_before(timestamp_ms)

    def flush_after_commit(self) -> None:
        pending, self._pending = self._pending, []
        if not pending:
            return
        try:
            self._connection.execute("BEGIN IMMEDIATE;")
            for event in pending:
                self._repository.append(event)
            self._connection.execute("COMMIT;")
        except Exception:
            if self._connection.in_transaction:
                self._connection.execute("ROLLBACK;")
            _LOGGER.exception("post-commit diagnostic trace persistence failed")

    def discard_pending(self) -> None:
        self._pending.clear()
