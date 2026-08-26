"""In-memory run event publisher used by the local FastAPI service."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from queue import Empty, Queue
from threading import Lock
from typing import cast

from google_work_agent.ports import (
    BufferStatus,
    InvalidReplayCursorError,
    PendingProjectionEvent,
    ProjectionEvent,
    RunEventSubscription,
    SnapshotRequiredReplayError,
)
from google_work_agent.ports.observability_events import sanitize_event_attributes


@dataclass(slots=True)
class _QueueSubscription:
    queue: Queue[ProjectionEvent]

    def poll(self, timeout_seconds: float) -> ProjectionEvent | None:
        try:
            return self.queue.get(timeout=timeout_seconds)
        except Empty:
            return None


class InMemorySseEventBuffer:
    """Run-scoped event buffer with monotonic ids and replay support."""

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
        self._buffers: dict[str, deque[ProjectionEvent]] = defaultdict(
            lambda: deque(maxlen=self._capacity_per_run)
        )
        self._subscribers: dict[str, list[_QueueSubscription]] = defaultdict(list)
        self._next_counter = 1
        self._lock = Lock()

    def publish(self, event: PendingProjectionEvent) -> ProjectionEvent:
        with self._lock:
            event_id = f"{self._service_instance_id}:{self._next_counter}"
            self._next_counter += 1
            sanitized = cast(
                dict[str, object],
                sanitize_event_attributes(event.payload).values,
            )
            published = ProjectionEvent(
                event_id=event_id,
                run_id=event.run_id,
                action_id=event.action_id,
                occurred_at_ms=event.occurred_at_ms,
                event_type=event.event_type,
                payload=sanitized,
                projection_version=event.projection_version,
                schema_version=event.schema_version,
            )
            buffer = self._buffers[event.run_id]
            buffer.append(published)
            subscribers = tuple(self._subscribers[event.run_id])
        for subscriber in subscribers:
            subscriber.queue.put_nowait(published)
        return published

    def replay(
        self,
        *,
        run_id: str,
        after_event_id: str | None,
    ) -> tuple[ProjectionEvent, ...]:
        with self._lock:
            buffer = tuple(self._buffers[run_id])
        if after_event_id is None:
            return buffer

        instance_id, counter = _parse_event_id(after_event_id)
        if instance_id != self._service_instance_id:
            raise SnapshotRequiredReplayError("event cursor belongs to another service instance")

        if not buffer:
            raise SnapshotRequiredReplayError("event buffer is empty")

        newest_counter = _parse_event_id(buffer[-1].event_id)[1]
        oldest_counter = _parse_event_id(buffer[0].event_id)[1]
        if counter > newest_counter:
            raise SnapshotRequiredReplayError("event cursor is ahead of the current buffer")
        if counter < oldest_counter - 1:
            raise SnapshotRequiredReplayError("event cursor has already been evicted")

        return tuple(event for event in buffer if _parse_event_id(event.event_id)[1] > counter)

    def subscribe(self, run_id: str) -> RunEventSubscription:
        subscription = _QueueSubscription(queue=Queue())
        with self._lock:
            self._subscribers[run_id].append(subscription)
        return subscription

    def get_buffer_status(self, run_id: str) -> BufferStatus:
        with self._lock:
            buffer = self._buffers[run_id]
            newest = buffer[-1].event_id if buffer else None
            return BufferStatus(
                run_id=run_id,
                service_instance_id=self._service_instance_id,
                newest_event_id=newest,
                event_count=len(buffer),
                capacity=self._capacity_per_run,
            )

    def close_subscription(self, subscription: RunEventSubscription) -> None:
        if not isinstance(subscription, _QueueSubscription):
            return
        with self._lock:
            for subscribers in self._subscribers.values():
                while subscription in subscribers:
                    subscribers.remove(subscription)


def _parse_event_id(event_id: str) -> tuple[str, int]:
    try:
        instance_id, raw_counter = event_id.split(":", 1)
        counter = int(raw_counter)
    except ValueError as error:
        raise InvalidReplayCursorError("invalid event cursor format") from error
    if not instance_id or counter < 1:
        raise InvalidReplayCursorError("invalid event cursor format")
    return instance_id, counter
