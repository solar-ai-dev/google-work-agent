"""Get durable replay semantics for one run event stream."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from google_work_agent.application.projections import build_snapshot_required_event
from google_work_agent.ports import (
    InvalidReplayCursorError,
    ProjectionEvent,
    QueryConnectionFactory,
    SseEventBufferPort,
    SnapshotRequiredReplayError,
)


@dataclass(frozen=True, slots=True)
class GetEventReplayQuery:
    run_id: str
    after_event_id: str | None


@dataclass(frozen=True, slots=True)
class GetEventReplayResult:
    run_exists: bool
    events: tuple[ProjectionEvent, ...]
    terminate_stream: bool
    snapshot_fallback: bool


class GetEventReplayHandler:
    """Own run existence, replay eligibility, and snapshot fallback decision."""

    def __init__(self, *, database_path: Path, connection_factory: QueryConnectionFactory, event_publisher: SseEventBufferPort, now_ms: Callable[[], int]) -> None:
        self._database_path = database_path
        self._connection_factory = connection_factory
        self._event_publisher = event_publisher
        self._now_ms = now_ms

    @classmethod
    def from_legacy_suppliers(cls, *, query_supplier: Callable[[], object], event_publisher_supplier: Callable[[], SseEventBufferPort], now_ms: Callable[[], int]) -> "GetEventReplayHandler":
        query = query_supplier()
        return cls(
            database_path=query._database_path,  # type: ignore[attr-defined]
            connection_factory=query._connection_factory,  # type: ignore[attr-defined]
            event_publisher=event_publisher_supplier(),
            now_ms=now_ms,
        )

    def __call__(self, query: GetEventReplayQuery) -> GetEventReplayResult:
        with self._connection_factory(self._database_path) as connection:
            exists = connection.execute("SELECT 1 FROM runs WHERE id = ? LIMIT 1;", (query.run_id,)).fetchone() is not None
        if not exists:
            return GetEventReplayResult(run_exists=False, events=(), terminate_stream=True, snapshot_fallback=False)
        try:
            events = self._event_publisher.replay(run_id=query.run_id, after_event_id=query.after_event_id)
            return GetEventReplayResult(run_exists=True, events=events, terminate_stream=False, snapshot_fallback=False)
        except (InvalidReplayCursorError, SnapshotRequiredReplayError) as error:
            fallback = build_snapshot_required_event(run_id=query.run_id, occurred_at_ms=self._now_ms(), reason=str(error))
            published = self._event_publisher.publish(fallback)
            return GetEventReplayResult(run_exists=True, events=(published,), terminate_stream=True, snapshot_fallback=True)
