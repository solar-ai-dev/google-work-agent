"""ResourceRef-owner-local persistence projection for external snapshots."""

from __future__ import annotations

from json import dumps

from google_work_agent.domain.resource_ref.model import ResourceRef as ResourceRefRecord
from google_work_agent.ports.connector.contracts.google_workspace import (
    ResourceSnapshot,
    ResourceType,
)

_DURABLE_RESOURCE_TYPES = frozenset(
    {
        ResourceType.GMAIL_DRAFT,
        ResourceType.GMAIL_MESSAGE,
        ResourceType.GMAIL_THREAD,
        ResourceType.TASK_LIST,
        ResourceType.TASK,
        ResourceType.CALENDAR,
        ResourceType.CALENDAR_EVENT,
    }
)


def is_durable_resource_type(resource_type: ResourceType) -> bool:
    """Return whether a Connector resource may be persisted as a ResourceRef."""

    return resource_type in _DURABLE_RESOURCE_TYPES


def minimal_resource_metadata(snapshot: ResourceSnapshot) -> dict[str, object]:
    """Return the bounded metadata whitelist stored with one ResourceRef.

    Provider payloads are never persisted wholesale. Fields here mirror the
    existing READ projection and contain only small identity/display or
    recovery-supporting facts; bodies, attachment bytes, page tokens, OAuth
    material, and arbitrary provider fields are intentionally excluded.
    """
    if snapshot.resource_type is ResourceType.GMAIL_MESSAGE:
        to_value = snapshot.payload.get("to")
        attachments_value = snapshot.payload.get("attachments")
        return {
            "from": _optional_text(snapshot.payload.get("from")),
            "to_count": len(to_value) if isinstance(to_value, list) else 0,
            "attachment_count": (
                len(attachments_value) if isinstance(attachments_value, list) else 0
            ),
        }
    if snapshot.resource_type is ResourceType.GMAIL_THREAD:
        participants = snapshot.payload.get("participants")
        return {
            "subject": _optional_text(snapshot.payload.get("subject")),
            "participant_count": len(participants) if isinstance(participants, list) else 0,
        }
    if snapshot.resource_type is ResourceType.TASK:
        return {
            "status": _optional_text(snapshot.payload.get("status")),
            "due": _optional_text(snapshot.payload.get("due")),
        }
    if snapshot.resource_type is ResourceType.CALENDAR_EVENT:
        return {
            "status": _optional_text(snapshot.payload.get("status")),
            "event_kind": _optional_text(snapshot.payload.get("event_kind")),
            "transparency": _optional_text(snapshot.payload.get("transparency")),
        }
    return {"title": snapshot_title(snapshot)}


def resource_ref_from_snapshot(
    *,
    run_id: str,
    connector_id: str,
    snapshot: ResourceSnapshot,
    captured_at_ms: int,
) -> ResourceRefRecord:
    """Build one durable minimal ResourceRef using explicit connector identity."""
    if not connector_id:
        raise ValueError("ResourceRef projection requires connector_id")
    if not is_durable_resource_type(snapshot.resource_type):
        raise ValueError(
            f"resource type is not durable ResourceRef material: {snapshot.resource_type.value}"
        )
    registry_resource_type = snapshot.resource_type.value
    title = snapshot_title(snapshot) or snapshot.resource_id
    return ResourceRefRecord(
        id=(
            f"resource-ref-{run_id}-{connector_id}-"
            f"{snapshot.resource_type.value}-{snapshot.resource_id}"
        ),
        run_id=run_id,
        connector_id=connector_id,
        resource_type=registry_resource_type,
        resource_id=snapshot.resource_id,
        parent_resource_id=snapshot.parent_id,
        canonical_url=None,
        title=title[:200],
        event_time_ms=None,
        version_token=snapshot.version,
        metadata_json=dumps(minimal_resource_metadata(snapshot), sort_keys=True),
        captured_at_ms=captured_at_ms,
    )


def snapshot_title(snapshot: ResourceSnapshot) -> str | None:
    for key in ("subject", "title", "snippet"):
        value = snapshot.payload.get(key)
        if isinstance(value, str) and value:
            return value[:200]
    return None


def _optional_text(value: object) -> str | None:
    """Persist only bounded provider text, never stringify containers/bytes."""
    if not isinstance(value, str):
        return None
    return value[:200]
