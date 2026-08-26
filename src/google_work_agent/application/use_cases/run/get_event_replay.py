"""Get durable replay semantics for one run event stream."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from google_work_agent.application.projections import build_snapshot_required_event
from google_work_agent.ports import (
    InvalidReplayCursorError,
    ProjectionEvent,
    SnapshotRequiredReplayError,
    SseEventBufferPort,
)
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


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

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        event_publisher: SseEventBufferPort,
        now_ms: Callable[[], int],
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._event_publisher = event_publisher
        self._now_ms = now_ms

    def __call__(self, query: GetEventReplayQuery) -> GetEventReplayResult:
        with self._unit_of_work_factory() as unit_of_work:
            exists = unit_of_work.runs.get(query.run_id) is not None
        if not exists:
            return GetEventReplayResult(
                run_exists=False,
                events=(),
                terminate_stream=True,
                snapshot_fallback=False,
            )
        try:
            events = self._event_publisher.replay(
                run_id=query.run_id, after_event_id=query.after_event_id
            )
            return GetEventReplayResult(
                run_exists=True,
                events=events,
                terminate_stream=False,
                snapshot_fallback=False,
            )
        except (InvalidReplayCursorError, SnapshotRequiredReplayError) as error:
            fallback = build_snapshot_required_event(
                run_id=query.run_id,
                occurred_at_ms=self._now_ms(),
                reason=str(error),
            )
            published = self._event_publisher.publish(fallback)
            return GetEventReplayResult(
                run_exists=True,
                events=(published,),
                terminate_stream=True,
                snapshot_fallback=True,
            )
