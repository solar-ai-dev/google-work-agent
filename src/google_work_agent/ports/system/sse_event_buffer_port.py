"""Run event publisher contracts for SSE projections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ProjectionEvent:
    """Sanitized SSE projection event."""

    event_id: str
    run_id: str
    occurred_at_ms: int
    event_type: str
    payload: dict[str, object]
    projection_version: int
    schema_version: int
    action_id: str | None = None


@dataclass(frozen=True, slots=True)
class PendingProjectionEvent:
    """Projection event before a publisher assigns a monotonic event id."""

    run_id: str
    occurred_at_ms: int
    event_type: str
    payload: dict[str, object]
    projection_version: int
    schema_version: int
    action_id: str | None = None


@dataclass(frozen=True, slots=True)
class BufferStatus:
    """Runtime view of one run-scoped event buffer."""

    run_id: str
    service_instance_id: str
    newest_event_id: str | None
    event_count: int
    capacity: int


class EventReplayError(RuntimeError):
    """Base class for replay cursor failures."""


class InvalidReplayCursorError(EventReplayError):
    """Raised when the caller supplied an invalid cursor."""


class SnapshotRequiredReplayError(EventReplayError):
    """Raised when replay cannot continue and the client must fetch a snapshot."""


class RunEventSubscription(Protocol):
    """Polling subscription used by the SSE route."""

    def poll(self, timeout_seconds: float) -> ProjectionEvent | None:
        """Return the next event if available."""


class SseEventBufferPort(Protocol):
    """Publish and replay run-scoped projection events."""

    def publish(self, event: PendingProjectionEvent) -> ProjectionEvent:
        """Publish one event and return the assigned event id."""

    def replay(
        self,
        *,
        run_id: str,
        after_event_id: str | None,
    ) -> tuple[ProjectionEvent, ...]:
        """Replay buffered events after one cursor."""

    def subscribe(self, run_id: str) -> RunEventSubscription:
        """Subscribe to future events for one run."""

    def get_buffer_status(self, run_id: str) -> BufferStatus:
        """Return buffer status for one run."""

    def close_subscription(self, subscription: RunEventSubscription) -> None:
        """Release a subscription."""
