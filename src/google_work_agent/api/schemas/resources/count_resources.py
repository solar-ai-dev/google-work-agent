"""Count-resources wire response."""

from typing import Literal

from google_work_agent.api.schemas.model import ApiModel


class ResourceCountResponse(ApiModel):
    schema_version: Literal[1]
    source: Literal["gmail", "tasks", "calendar"]
    exact_count: int
    as_of_ms: int
