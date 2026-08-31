"""Canonical Run-scoped SSE wire envelope."""

from typing import Literal

from google_work_agent.api.schemas.model import ApiModel


class RunSseEventResponseV1(ApiModel):
    schema_version: Literal[1]
    event_id: str
    run_id: str
    action_id: str | None
    occurred_at_ms: int
    event_type: str
    payload: dict[str, object]
    projection_version: int


__all__ = ["RunSseEventResponseV1"]
