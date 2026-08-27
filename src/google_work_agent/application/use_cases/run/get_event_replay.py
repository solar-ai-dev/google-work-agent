"""Get durable replay semantics for one run event stream."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from google_work_agent.ports import (
    RunSseEventV1,
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
    events: tuple[RunSseEventV1, ...]
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
        page = self._event_publisher.list_after(query.run_id, query.after_event_id, 128)
        return GetEventReplayResult(
            run_exists=True,
            events=page.events,
            terminate_stream=page.cursor_status == "CURSOR_EXPIRED",
            snapshot_fallback=page.cursor_status == "CURSOR_EXPIRED",
        )
