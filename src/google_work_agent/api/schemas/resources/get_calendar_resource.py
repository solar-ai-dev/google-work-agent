"""Calendar resource-detail wire response."""

from typing import Literal

from google_work_agent.api.schemas.model import ApiModel


class CalendarResourceDetailResponseV1(ApiModel):
    schema_version: Literal[1]
    resource_id: str
    title: str
    start: str
    end: str
    timezone: str
    calendar_id: str
    attendees: list[str]
    location: str | None
    description: str | None


__all__ = ["CalendarResourceDetailResponseV1"]
