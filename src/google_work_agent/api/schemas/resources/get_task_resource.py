"""Task resource-detail wire response."""

from typing import Literal

from google_work_agent.api.schemas.model import ApiModel


class TaskResourceDetailResponseV1(ApiModel):
    schema_version: Literal[1]
    resource_id: str
    title: str
    task_status: Literal["incomplete", "completed"]
    scheduled_date: str | None
    completed_at: str | None
    tasklist_id: str
    notes: str | None


__all__ = ["TaskResourceDetailResponseV1"]
