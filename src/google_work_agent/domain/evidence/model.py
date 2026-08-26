"""Evidence domain model."""

from dataclasses import dataclass
from enum import StrEnum


class EvidenceOriginType(StrEnum):
    GOOGLE_RESOURCE = "GOOGLE_RESOURCE"
    USER_MESSAGE = "USER_MESSAGE"
    DERIVED = "DERIVED"


@dataclass(frozen=True, slots=True)
class Evidence:
    id: str
    run_id: str
    origin_type: EvidenceOriginType
    resource_ref_id: str | None
    message_id: str | None
    kind: str
    excerpt: str
    locator_json: str | None
    created_at_ms: int
