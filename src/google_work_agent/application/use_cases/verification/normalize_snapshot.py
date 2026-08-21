"""Canonical projection used by verification and recovery reads."""

from google_work_agent.ports import ResourceSnapshot


def normalize_snapshot(snapshot: ResourceSnapshot) -> dict[str, object]:
    payload = dict(snapshot.payload)
    payload.pop("recovery_fingerprint", None)
    return {
        "resource_type": snapshot.resource_type.value,
        "resource_id": snapshot.resource_id,
        "parent_id": snapshot.parent_id,
        "version": snapshot.version,
        "payload": payload,
    }
