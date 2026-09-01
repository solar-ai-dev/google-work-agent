"""Resource-reference domain model."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ResourceRef:
    id: str
    run_id: str
    connector_id: str
    resource_type: str
    resource_id: str
    parent_resource_id: str | None
    canonical_url: str | None
    title: str | None
    event_time_ms: int | None
    version_token: str | None
    metadata_json: str
    captured_at_ms: int
