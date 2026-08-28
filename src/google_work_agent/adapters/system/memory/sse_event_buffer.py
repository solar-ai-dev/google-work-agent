"""In-memory bounded SSE event buffer and transport subscriptions."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, replace
from queue import Empty, Queue
from threading import Lock
from typing import Literal, cast

from google_work_agent.ports.events.observability_events import sanitize_event_attributes
from google_work_agent.ports.system.sse_event_buffer_port import (
    RunSseEventV1,
    SseEventBufferPort,
    SseEventPageV1,
)


@dataclass(slots=True)
class SseTransportSubscription:
    queue: Queue[RunSseEventV1]

    def poll(self, timeout_seconds: float) -> RunSseEventV1 | None:
        try:
            return self.queue.get(timeout=timeout_seconds)
        except Empty:
            return None


class InMemorySseEventBuffer(SseEventBufferPort):
    def __init__(
        self,
        *,
        service_instance_id: str,
        capacity_per_run: int = 128,
    ) -> None:
        if capacity_per_run < 1:
            raise ValueError("capacity_per_run must be positive")
        self._service_instance_id = service_instance_id
        self._capacity_per_run = capacity_per_run
        self._buffers: dict[str, deque[RunSseEventV1]] = defaultdict(
            lambda: deque(maxlen=self._capacity_per_run)
        )
        self._subscribers: dict[str, list[SseTransportSubscription]] = defaultdict(list)
        self._next_counter = 1
        self._lock = Lock()

    def append(self, event: RunSseEventV1) -> None:
        with self._lock:
            event_id = f"{self._service_instance_id}:{self._next_counter}"
            self._next_counter += 1
            sanitized = cast(dict[str, object], sanitize_event_attributes(event.payload).values)
            published = replace(event, event_id=event_id, payload=sanitized)
            self._buffers[event.run_id].append(published)
            subscribers = tuple(self._subscribers[event.run_id])
        for subscriber in subscribers:
            subscriber.queue.put_nowait(published)

    def list_after(self, run_id: str, last_event_id: str | None, limit: int) -> SseEventPageV1:
        if limit < 1:
            raise ValueError("SSE replay limit must be positive")
        limit = min(limit, self._capacity_per_run)
        with self._lock:
            buffer = tuple(self._buffers.get(run_id, ()))
        if last_event_id is None:
            selected = buffer[:limit]
            return _page(selected, buffer, "OK")
        cursor = _parse_event_id(last_event_id)
        if cursor is None or cursor[0] != self._service_instance_id or not buffer:
            return _page((), buffer, "CURSOR_EXPIRED")
        oldest = _parse_event_id(buffer[0].event_id)
        newest = _parse_event_id(buffer[-1].event_id)
        if oldest is None or newest is None or cursor[1] < oldest[1] - 1 or cursor[1] > newest[1]:
            return _page((), buffer, "CURSOR_EXPIRED")
        selected = tuple(
            event for event in buffer if (_parse_event_id(event.event_id) or ("", 0))[1] > cursor[1]
        )[:limit]
        return _page(selected, buffer, "OK")

    def clear_run(self, run_id: str) -> None:
        with self._lock:
            self._buffers.pop(run_id, None)

    # Transport-only helpers; they are intentionally absent from SseEventBufferPort.
    def subscribe(self, run_id: str) -> SseTransportSubscription:
        subscription = SseTransportSubscription(queue=Queue())
        with self._lock:
            self._subscribers[run_id].append(subscription)
        return subscription

    def close_subscription(self, subscription: SseTransportSubscription) -> None:
        with self._lock:
            for subscriptions in self._subscribers.values():
                while subscription in subscriptions:
                    subscriptions.remove(subscription)


def _page(
    selected: tuple[RunSseEventV1, ...],
    full_buffer: tuple[RunSseEventV1, ...],
    status: str,
) -> SseEventPageV1:
    next_event_id = selected[-1].event_id if selected else None
    if selected and full_buffer and selected[-1] == full_buffer[-1]:
        next_event_id = None
    return SseEventPageV1(
        schema_version=1,
        events=selected,
        next_event_id=next_event_id,
        cursor_status=cast(Literal["OK", "CURSOR_EXPIRED"], status),
    )


def _parse_event_id(event_id: str) -> tuple[str, int] | None:
    try:
        instance_id, raw_counter = event_id.split(":", 1)
        counter = int(raw_counter)
    except ValueError:
        return None
    if not instance_id or counter < 1:
        return None
    return instance_id, counter


__all__ = ["InMemorySseEventBuffer", "SseTransportSubscription"]
