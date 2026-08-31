"""Task-list container wire response."""

from typing import Literal

from google_work_agent.api.schemas.model import ApiModel


class TaskListContainerItemV1(ApiModel):
    schema_version: Literal[1]
    tasklist_id: str
    title: str


class TaskListContainerListResponseV1(ApiModel):
    schema_version: Literal[1]
    items: list[TaskListContainerItemV1]
    next_page_token: str | None


__all__ = ["TaskListContainerItemV1", "TaskListContainerListResponseV1"]
