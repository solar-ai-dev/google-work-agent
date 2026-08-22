"""Canonical latest-run-for-conversation query."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from google_work_agent.ports import QueryConnectionFactory


@dataclass(frozen=True, slots=True)
class GetLatestRunQuery:
    conversation_id: str


@dataclass(frozen=True, slots=True)
class GetLatestRunResult:
    run_id: str
    status: str
    version: int
    started_at_ms: int


class GetLatestRunHandler:
    def __init__(self, *, database_path: Path, connection_factory: QueryConnectionFactory) -> None:
        self._database_path = database_path
        self._connection_factory = connection_factory

    @classmethod
    def from_legacy_query_supplier(cls, supplier: Callable[[], object]) -> "GetLatestRunHandler":
        query = supplier()
        return cls(
            database_path=getattr(query, "_database_path"),
            connection_factory=getattr(query, "_connection_factory"),
        )

    def __call__(self, query: GetLatestRunQuery) -> GetLatestRunResult | None:
        with self._connection_factory(self._database_path) as connection:
            row = connection.execute(
                """
                SELECT id, status, version, started_at_ms
                FROM runs
                WHERE conversation_id = ?
                ORDER BY started_at_ms DESC, id DESC
                LIMIT 1;
                """,
                (query.conversation_id,),
            ).fetchone()
        if row is None:
            return None
        return GetLatestRunResult(
            run_id=str(row["id"]),
            status=str(row["status"]),
            version=int(row["version"]),
            started_at_ms=int(row["started_at_ms"]),
        )
