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


class TraceRepository(Protocol):
    def append(self, event: TraceEventRecord) -> None: ...
    def add(self, event: TraceEventRecord) -> None: ...
    def list_by_run_after_cursor(
        self, *, run_id: str, cursor_after: int | None, limit: int = 100
    ) -> tuple[PersistedTraceEventRecord, ...]: ...
    def list_before_retention_cutoff(
        self, *, cutoff_ms: int, limit: int
    ) -> tuple[PersistedTraceEventRecord, ...]: ...
    def purge_before_cutoff(self, *, cutoff_ms: int, limit: int) -> int: ...
