"""Bounded process-local SSE projection replay boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True, slots=True)
class RunSseEventV1:
    schema_version: Literal[1]
    event_id: str
    run_id: str
    action_id: str | None
    occurred_at_ms: int
    event_type: str
    payload: dict[str, object]
    projection_version: int


@dataclass(frozen=True, slots=True)
class SseEventPageV1:
    schema_version: Literal[1]
    events: tuple[RunSseEventV1, ...]
    next_event_id: str | None
    cursor_status: Literal["OK", "CURSOR_EXPIRED"]


class SseEventBufferPort(Protocol):
    def append(self, event: RunSseEventV1) -> None: ...

    def list_after(self, run_id: str, last_event_id: str | None, limit: int) -> SseEventPageV1: ...

    def clear_run(self, run_id: str) -> None: ...


__all__ = ["RunSseEventV1", "SseEventBufferPort", "SseEventPageV1"]
