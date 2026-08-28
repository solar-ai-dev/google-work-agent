"""Count external resources through the canonical resource query boundary."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from google_work_agent.ports.connector.connector_failure import (
    ConnectorFailureCode,
    ConnectorOperationFailure,
    normalize_google_workspace_failure,
)
from google_work_agent.ports.connector.contracts.google_workspace import (
    GoogleWorkspaceGatewayError,
    ResourcePage,
)

MAX_RESOURCE_PAGE_SIZE = 100
GMAIL_PRIMARY_QUERY = "in:inbox category:primary"


@dataclass(frozen=True, slots=True)
class ResourceCount:
    source: str
    total_count: int


class CountResourceAccess(Protocol):
    def count_gmail_page(
        self,
        *,
        query: str,
        page_token: str | None,
        page_size: int,
        include_thread_metadata: bool,
    ) -> ResourcePage: ...

    def count_task_lists_page(
        self,
        *,
        page_token: str | None,
        page_size: int,
    ) -> ResourcePage: ...

    def count_tasks_page(
        self,
        *,
        task_list_id: str,
        page_token: str | None,
        page_size: int,
        show_completed: bool,
    ) -> ResourcePage: ...

    def count_calendar_events_page(
        self,
        *,
        calendar_id: str,
        page_token: str | None,
        page_size: int,
        time_min: str,
        time_max: str,
        single_events: bool,
        order_by: str,
    ) -> ResourcePage: ...

    def default_task_list_id(self) -> str | None: ...

    def default_calendar_id(self) -> str | None: ...

    def timezone_name(self) -> str: ...

    def current_time(self) -> datetime: ...


@dataclass(frozen=True, slots=True)
class GetResourceCountQuery:
    source: str
    query: str = ""
    task_list_id: str | None = None
    calendar_id: str | None = None
    time_min: str | None = None
    time_max: str | None = None


@dataclass(frozen=True, slots=True)
class GetResourceCountResult:
    count: ResourceCount


@dataclass(frozen=True, slots=True)
class GetResourceCountHandler:
    access: CountResourceAccess

    def __call__(self, query: GetResourceCountQuery) -> GetResourceCountResult:
        try:
            if query.source == "gmail":
                count = ResourceCount(
                    source="gmail",
                    total_count=_count_pages(
                        lambda page_token: self.access.count_gmail_page(
                            query=query.query.strip() or GMAIL_PRIMARY_QUERY,
                            page_token=page_token,
                            page_size=MAX_RESOURCE_PAGE_SIZE,
                            include_thread_metadata=False,
                        )
                    ),
                )
            elif query.source == "tasks":
                count = ResourceCount(source="tasks", total_count=self._count_tasks(query))
            elif query.source == "calendar":
                count = ResourceCount(source="calendar", total_count=self._count_calendar(query))
            else:
                raise ConnectorOperationFailure(
                    code=ConnectorFailureCode.NOT_FOUND,
                    detail_code="RESOURCE_SOURCE_NOT_FOUND",
                )
        except GoogleWorkspaceGatewayError as error:
            raise normalize_google_workspace_failure(error) from error
        except ValueError as error:
            raise ConnectorOperationFailure(
                code=ConnectorFailureCode.INVALID_ARGUMENT,
                detail_code="RESOURCE_QUERY_INVALID",
            ) from error
        return GetResourceCountResult(count=count)

    def _count_tasks(self, query: GetResourceCountQuery) -> int:
        task_list_id = query.task_list_id or self.access.default_task_list_id()
        if task_list_id is None:
            task_lists = self.access.count_task_lists_page(page_token=None, page_size=1)
            if not task_lists.items:
                return 0
            task_list_id = task_lists.items[0].resource_id
        return _count_pages(
            lambda page_token: self.access.count_tasks_page(
                task_list_id=task_list_id,
                page_token=page_token,
                page_size=MAX_RESOURCE_PAGE_SIZE,
                show_completed=False,
            )
        )

    def _count_calendar(self, query: GetResourceCountQuery) -> int:
        calendar_id = query.calendar_id or self.access.default_calendar_id() or "primary"
        time_min, time_max = _resolve_calendar_window(
            query.time_min,
            query.time_max,
            now=self.access.current_time(),
            timezone_name=self.access.timezone_name(),
        )
        return _count_pages(
            lambda page_token: self.access.count_calendar_events_page(
                calendar_id=calendar_id,
                page_token=page_token,
                page_size=MAX_RESOURCE_PAGE_SIZE,
                time_min=time_min,
                time_max=time_max,
                single_events=True,
                order_by="startTime",
            )
        )


def _count_pages(fetch_page: Callable[[str | None], ResourcePage]) -> int:
    page_token: str | None = None
    total_count = 0
    while True:
        page = fetch_page(page_token)
        total_count += len(page.items)
        page_token = page.next_page_token
        if page_token is None:
            return total_count


def _resolve_calendar_window(
    time_min: str | None,
    time_max: str | None,
    *,
    now: datetime,
    timezone_name: str,
) -> tuple[str, str]:
    if (time_min is None) != (time_max is None):
        raise ValueError("time_min and time_max must be provided together")
    if time_min is not None and time_max is not None:
        return time_min, time_max
    window_start = now.astimezone(ZoneInfo(timezone_name))
    return (
        window_start.isoformat(timespec="seconds"),
        (window_start + timedelta(days=90)).isoformat(timespec="seconds"),
    )
