"""Calendar container wire response."""

from typing import Literal

from google_work_agent.api.schemas.model import ApiModel


class CalendarContainerItemV1(ApiModel):
    schema_version: Literal[1]
    calendar_id: str
    title: str
    primary: bool


class CalendarContainerListResponseV1(ApiModel):
    schema_version: Literal[1]
    items: list[CalendarContainerItemV1]
    next_page_token: str | None


__all__ = ["CalendarContainerItemV1", "CalendarContainerListResponseV1"]
