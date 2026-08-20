"""Deterministic minimal persistence projection for external resource snapshots."""

from __future__ import annotations

from json import dumps

from google_work_agent.ports import (
    ResourceRefRecord,
    ResourceSnapshot,
    ResourceSource,
    ResourceType,
    StoredResourceType,
)


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
            "from": _optional_str(snapshot.payload.get("from")),
            "to_count": len(to_value) if isinstance(to_value, list) else 0,
            "attachment_count": (
                len(attachments_value) if isinstance(attachments_value, list) else 0
            ),
        }
    if snapshot.resource_type is ResourceType.GMAIL_THREAD:
        participants = snapshot.payload.get("participants")
        return {
            "subject": _optional_str(snapshot.payload.get("subject")),
            "participant_count": len(participants) if isinstance(participants, list) else 0,
        }
    if snapshot.resource_type is ResourceType.TASK:
        return {
            "status": _optional_str(snapshot.payload.get("status")),
            "due": snapshot.payload.get("due"),
        }
    if snapshot.resource_type is ResourceType.CALENDAR_EVENT:
        return {
            "status": _optional_str(snapshot.payload.get("status")),
            "event_kind": _optional_str(snapshot.payload.get("event_kind")),
            "transparency": _optional_str(snapshot.payload.get("transparency")),
        }
    return {"title": snapshot_title(snapshot)}


def resource_ref_from_snapshot(
    *,
    run_id: str,
    snapshot: ResourceSnapshot,
    captured_at_ms: int,
) -> ResourceRefRecord:
    """Build the durable Google compatibility ResourceRef without raw payload storage.

    Connector-neutral identity persistence is owned by the connector-aware
    schema migration. Until Task 5 supplies connector_id on the runtime action
    contract, this function intentionally does not infer connector identity
    from ``source``.
    """
    source_map = {
        ResourceType.GMAIL_DRAFT: (ResourceSource.GMAIL, StoredResourceType.MESSAGE),
        ResourceType.GMAIL_MESSAGE: (ResourceSource.GMAIL, StoredResourceType.MESSAGE),
        ResourceType.TASK: (ResourceSource.TASKS, StoredResourceType.TASK),
        ResourceType.CALENDAR_EVENT: (ResourceSource.CALENDAR, StoredResourceType.EVENT),
    }
    source, stored_resource_type = source_map[snapshot.resource_type]
    title = snapshot_title(snapshot) or snapshot.resource_id
    return ResourceRefRecord(
        id=f"resource-ref-{run_id}-{snapshot.resource_type.value}-{snapshot.resource_id}",
        run_id=run_id,
        source=source,
        resource_type=stored_resource_type,
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


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
