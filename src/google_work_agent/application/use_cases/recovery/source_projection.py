"""Recovery-owner-local source snapshot projection."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

_RESOURCE_SOURCE_FIELDS = (
    "resource_type",
    "resource_id",
    "parent_id",
    "version",
    "payload",
)


def project_source_resource(source_snapshot: Mapping[str, object]) -> dict[str, object] | None:
    """Return only authoritative provider-resource fields from an Approval snapshot.

    Approval ``source_snapshot_json`` can also contain policy/approval authority
    metadata. Recovery must never compare those top-level metadata fields with
    a provider ``ResourceSnapshot``. The resource proof is usable only when the
    DB-contract identity/version pair is present; otherwise UPDATE recovery
    cannot prove that the write was definitively not sent.
    """

    resource_id = source_snapshot.get("resource_id")
    version = source_snapshot.get("version")
    if not isinstance(resource_id, str) or not resource_id:
        return None
    if not isinstance(version, str) or not version:
        return None

    payload = source_snapshot.get("payload")
    if payload is not None and not isinstance(payload, Mapping):
        return None

    projection = {
        field: source_snapshot[field]
        for field in _RESOURCE_SOURCE_FIELDS
        if field in source_snapshot
    }
    if isinstance(payload, Mapping):
        projection["payload"] = {
            str(key): value for key, value in cast(Mapping[object, object], payload).items()
        }
    return projection


__all__ = ["project_source_resource"]
