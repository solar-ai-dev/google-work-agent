"""Projection helpers for the local API and SSE events."""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from json import dumps
from typing import Any, cast

from google_work_agent.application.observability import sanitize_event_attributes
from google_work_agent.ports import PendingProjectionEvent

PROJECTION_SCHEMA_VERSION = 1
PROJECTION_VERSION = 1


@dataclass(frozen=True, slots=True)
class SnapshotRequiredPayload:
    """Payload emitted when replay must fall back to a snapshot query."""

    reason: str


def build_projection_event(
    *,
    run_id: str,
    occurred_at_ms: int,
    event_type: str,
    payload: dict[str, object] | object,
    action_id: str | None = None,
) -> PendingProjectionEvent:
    """Create a sanitized projection event ready for publication."""

    return PendingProjectionEvent(
        run_id=run_id,
        action_id=action_id,
        occurred_at_ms=occurred_at_ms,
        event_type=event_type,
        payload=_coerce_payload(payload),
        projection_version=PROJECTION_VERSION,
        schema_version=PROJECTION_SCHEMA_VERSION,
    )


def build_snapshot_required_event(
    *,
    run_id: str,
    occurred_at_ms: int,
    reason: str,
) -> PendingProjectionEvent:
    """Create a replay fallback event."""

    return build_projection_event(
        run_id=run_id,
        occurred_at_ms=occurred_at_ms,
        event_type="snapshot_required",
        payload=SnapshotRequiredPayload(reason=reason),
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
