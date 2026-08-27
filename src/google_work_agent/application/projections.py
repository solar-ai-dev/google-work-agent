"""Projection helpers for the local API and SSE events."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from json import dumps
from typing import Any, cast

from google_work_agent.ports.observability_events import sanitize_event_attributes
from google_work_agent.ports.system.sse_event_buffer_port import RunSseEventV1

PROJECTION_SCHEMA_VERSION = 1
PROJECTION_VERSION = 1


def build_projection_event(
    *,
    run_id: str,
    occurred_at_ms: int,
    event_type: str,
    payload: dict[str, object] | object,
    action_id: str | None = None,
) -> RunSseEventV1:
    """Create a sanitized projection event ready for publication."""

    return RunSseEventV1(
        event_id="",
        run_id=run_id,
        action_id=action_id,
        occurred_at_ms=occurred_at_ms,
        event_type=event_type,
        payload=_coerce_payload(payload),
        projection_version=PROJECTION_VERSION,
        schema_version=PROJECTION_SCHEMA_VERSION,
    )


def serialize_projection_payload(payload: dict[str, object]) -> str:
    """Serialize one sanitized projection payload."""

    return dumps(payload, sort_keys=True)


def _coerce_payload(payload: dict[str, object] | object) -> dict[str, object]:
    if isinstance(payload, dict):
        raw = payload
    elif is_dataclass(payload) and not isinstance(payload, type):
        raw = cast(dict[str, object], asdict(cast(Any, payload)))
    else:
        raise TypeError("projection payload must be a dict or dataclass")
    return cast(dict[str, object], sanitize_event_attributes(raw).values)
