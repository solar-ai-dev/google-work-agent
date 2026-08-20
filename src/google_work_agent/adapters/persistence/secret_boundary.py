"""Persistence-side defense in depth for Trace/Audit secret boundaries."""

from __future__ import annotations

from dataclasses import replace
from json import JSONDecodeError, dumps, loads
from typing import Any

from google_work_agent.adapters.persistence.repositories import (
    SQLiteAuditRepository,
    SQLiteTraceRepository,
)
from google_work_agent.ports import AuditEventRecord, TraceEventRecord

_SENSITIVE_KEY_FRAGMENTS = (
    "page_token",
    "attachment_bytes",
    "raw_attachment",
    "provider_payload",
    "raw_provider_response",
    "raw_provider_request",
)
_SENSITIVE_VALUE_FRAGMENTS = (
    "canary_access_token",
    "canary_refresh_token",
    "canary_api_key",
    "canary_provider_page_token",
    "canary_attachment_bytes",
    "canary_provider_payload",
    "canary_raw_provider_response",
)
_REDACTED = "[REDACTED]"


class SecretBoundaryAuditRepository(SQLiteAuditRepository):
    """Audit repository that removes provider/session secret material before persistence."""

    def add(self, event: AuditEventRecord) -> None:
        super().add(
            replace(
                event,
                metadata_json=_scrub_event_json(event.metadata_json),
            )
        )


class SecretBoundaryTraceRepository(SQLiteTraceRepository):
    """Trace repository that removes provider/session secret material before persistence."""

    def add(self, event: TraceEventRecord) -> None:
        super().add(
            replace(
                event,
                payload_json=_scrub_event_json(event.payload_json),
            )
        )


def _scrub_event_json(raw: str) -> str:
    try:
        value = loads(raw)
    except (JSONDecodeError, TypeError):
        return raw
    cleaned = _scrub_value(value)
    return dumps(cleaned, sort_keys=True, separators=(",", ":"))


def _scrub_value(value: Any) -> Any:
    if isinstance(value, dict):
        attachment_projection = _looks_like_attachment_projection(value)
        result: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if any(fragment in normalized for fragment in _SENSITIVE_KEY_FRAGMENTS):
                continue
            if attachment_projection and normalized == "data":
                continue
            result[str(key)] = _scrub_value(item)
        return result
    if isinstance(value, list):
        return [_scrub_value(item) for item in value]
    if isinstance(value, str):
        lowered = value.lower()
        if any(fragment in lowered for fragment in _SENSITIVE_VALUE_FRAGMENTS):
            return _REDACTED
        return value
    return value


def _looks_like_attachment_projection(value: dict[object, object]) -> bool:
    normalized_keys = {
        str(key).strip().lower().replace("-", "_")
        for key in value
    }
    return "data" in normalized_keys and bool(
        {"filename", "mime_type", "attachment_id"} & normalized_keys
    )
