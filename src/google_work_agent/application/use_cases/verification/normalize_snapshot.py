"""Canonical projection used by verification and recovery reads."""

from dataclasses import dataclass

from google_work_agent.ports.connector.contracts.google_workspace import ResourceSnapshot


@dataclass(frozen=True, slots=True)
class NormalizeSnapshotQuery:
    snapshot: ResourceSnapshot


@dataclass(frozen=True, slots=True)
class NormalizeSnapshotResult:
    projection: dict[str, object]


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


class NormalizeSnapshotHandler:
    def __call__(self, query: NormalizeSnapshotQuery) -> NormalizeSnapshotResult:
        return NormalizeSnapshotResult(projection=normalize_snapshot(query.snapshot))
