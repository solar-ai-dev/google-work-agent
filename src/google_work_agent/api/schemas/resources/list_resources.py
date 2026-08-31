"""Closed resource-list wire response."""

from typing import Literal

from google_work_agent.api.schemas.model import ApiModel


class GmailListItemV1(ApiModel):
    schema_version: Literal[1]
    selection_handle: str
    resource_id: str
    subject: str
    sender_name: str | None
    sender_email: str | None
    received_at: str | None
    snippet: str | None
    has_attachments: bool


class TaskListItemV1(ApiModel):
    schema_version: Literal[1]
    selection_handle: str
    resource_id: str
    title: str
    task_status: Literal["incomplete", "completed"]
    scheduled_date: str | None
    completed_at: str | None
    tasklist_id: str


class CalendarListItemV1(ApiModel):
    schema_version: Literal[1]
    selection_handle: str
    resource_id: str
    title: str
    start: str
    end: str
    timezone: str
    calendar_id: str
    location: str | None


ResourceListItemV1 = GmailListItemV1 | TaskListItemV1 | CalendarListItemV1


class ResourceListResponse(ApiModel):
    schema_version: Literal[1]
    items: list[ResourceListItemV1]
    next_page_token: str | None
    total_count: int | None
    projection_version: str


__all__ = [
    "CalendarListItemV1",
    "GmailListItemV1",
    "ResourceListItemV1",
    "ResourceListResponse",
    "TaskListItemV1",
]
