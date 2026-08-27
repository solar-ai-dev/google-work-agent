"""Trace-event persistence port."""

from dataclasses import dataclass
from typing import Protocol

from google_work_agent.domain.trace_event.model import TraceEvent as TraceEventRecord


@dataclass(frozen=True, slots=True)
class PersistedTraceEventRecord:
    id: int
    run_id: str
    action_id: str | None
    event_type: str
    status: str | None
    duration_ms: int | None
    payload_json: str
    created_at_ms: int


@dataclass(frozen=True, slots=True)
class TraceEventCursor:
    run_id: str | None = None
    after_id: int | None = None


class TraceEventRepository(Protocol):
    def append(self, event: TraceEventRecord) -> None: ...
    def list_page(
        self, cursor: TraceEventCursor | None, limit: int
    ) -> tuple[PersistedTraceEventRecord, ...]: ...
    def purge_before(self, timestamp_ms: int) -> int: ...
