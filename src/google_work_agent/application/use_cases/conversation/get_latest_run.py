"""Canonical latest-run-for-conversation query."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


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
    def __init__(self, *, unit_of_work_factory: Callable[[], UnitOfWork]) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def __call__(self, query: GetLatestRunQuery) -> GetLatestRunResult | None:
        with self._unit_of_work_factory() as unit_of_work:
            run = unit_of_work.runs.get_latest_by_conversation(query.conversation_id)
        if run is None:
            return None
        return GetLatestRunResult(
            run_id=run.id,
            status=run.status.value,
            version=run.version,
            started_at_ms=run.started_at_ms,
        )
