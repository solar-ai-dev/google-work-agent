"""Canonical latest-run-for-conversation query."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from google_work_agent.application.queries import QueryService


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
    def __init__(self, *, query_service: Callable[[], QueryService]) -> None:
        self._query_service = query_service

    def __call__(self, query: GetLatestRunQuery) -> GetLatestRunResult | None:
        run = self._query_service().get_latest_run_for_conversation(query.conversation_id)
        if run is None:
            return None
        return GetLatestRunResult(
            run_id=run.run_id,
            status=run.status,
            version=run.version,
            started_at_ms=run.started_at_ms,
        )
