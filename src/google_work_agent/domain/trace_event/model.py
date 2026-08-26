"""Trace-event domain model."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TraceEvent:
    run_id: str
    action_id: str | None
    event_type: str
    status: str | None
    duration_ms: int | None
    payload_json: str
    created_at_ms: int
