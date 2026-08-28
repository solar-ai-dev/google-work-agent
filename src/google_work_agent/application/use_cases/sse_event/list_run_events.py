"""List bounded process-local SSE events for an existing Run."""

from collections.abc import Callable
from dataclasses import dataclass

from google_work_agent.ports.persistence.unit_of_work import UnitOfWork
from google_work_agent.ports.system.sse_event_buffer_port import (
    RunSseEventV1,
    SseEventBufferPort,
)


@dataclass(frozen=True, slots=True)
class ListRunEventsQuery:
    run_id: str
    last_event_id: str | None = None
    limit: int = 128


@dataclass(frozen=True, slots=True)
class ListRunEventsResult:
    run_exists: bool
    events: tuple[RunSseEventV1, ...]
    cursor_status: str
    next_event_id: str | None


class ListRunEventsHandler:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        event_buffer: SseEventBufferPort,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._event_buffer = event_buffer

    def __call__(self, query: ListRunEventsQuery) -> ListRunEventsResult:
        with self._unit_of_work_factory() as unit_of_work:
            exists = unit_of_work.runs.get(query.run_id) is not None
        if not exists:
            return ListRunEventsResult(False, (), "OK", None)
        page = self._event_buffer.list_after(query.run_id, query.last_event_id, query.limit)
        return ListRunEventsResult(True, page.events, page.cursor_status, page.next_event_id)


__all__ = ["ListRunEventsHandler", "ListRunEventsQuery", "ListRunEventsResult"]
