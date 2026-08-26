"""Resource-reference domain model."""

from dataclasses import dataclass
from enum import StrEnum


class ResourceSource(StrEnum):
    GMAIL = "GMAIL"
    TASKS = "TASKS"
    CALENDAR = "CALENDAR"


@dataclass(frozen=True, slots=True)
class ResourceRef:
    id: str
    run_id: str
    connector_id: str
    source: ResourceSource
    resource_type: str
    resource_id: str
    parent_resource_id: str | None
    canonical_url: str | None
    title: str | None
    event_time_ms: int | None
    version_token: str | None
    metadata_json: str
    captured_at_ms: int
