"""Compatibility façade and narrow Google resource access for canonical use cases."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from google_work_agent.application.use_cases.resource_ref.count_resources import (
    CountResourcesHandler,
    CountResourcesQuery,
    ResourceCount,
)
from google_work_agent.application.use_cases.resource_ref.get_resource import (
    GetResourceHandler,
    GetResourceQuery,
    GmailResourceDetail,
    _gmail_search_permalink,
)
from google_work_agent.application.use_cases.resource_ref.list_resources import (
    GMAIL_PRIMARY_QUERY,
    MAX_RESOURCE_PAGE_SIZE,
    ListResourcesHandler,
    ListResourcesQuery,
    ResourceListItem,
    ResourceListPage,
)
from google_work_agent.ports import (
    GmailThreadDetail,
    GmailUiReadGateway,
    GoogleWorkspaceGateway,
    ResourcePage,
)


class ResourceQueryService:
    """Legacy-compatible façade over narrow connector/config/time access.

    Canonical resource semantics live in application.use_cases.resource_ref.
    The methods ending in ``_page`` and the config/time accessors are narrow
    collaborators used by those canonical handlers. The historical public
    list/count/detail methods delegate back into the canonical handlers.
    """

    def __init__(
        self,
        *,
        gateway: GoogleWorkspaceGateway,
        gmail_detail_gateway: GmailUiReadGateway | None = None,
        default_calendar_id_provider: Callable[[], str | None] | None = None,
        default_tasklist_id_provider: Callable[[], str | None] | None = None,
        timezone_provider: Callable[[], str] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._gateway = gateway
        self._gmail_detail_gateway = gmail_detail_gateway
        self._default_calendar_id_provider = default_calendar_id_provider
        self._default_tasklist_id_provider = default_tasklist_id_provider
        self._now = now or (lambda: datetime.now(UTC))
        self._timezone_provider = timezone_provider or (lambda: "UTC")

    # Narrow canonical collaborators.

    def get_gmail_thread_detail_raw(self, *, resource_id: str) -> GmailThreadDetail:
        if self._gmail_detail_gateway is None:
            raise RuntimeError("Gmail detail provider is not configured")
        return self._gmail_detail_gateway.get_thread_detail(thread_id=resource_id)

    def list_gmail_page(
        self,
        *,
        query: str,
        page_token: str | None,
        page_size: int,
        include_thread_metadata: bool,
        continuation_scope: tuple[str, ...],
    ) -> ResourcePage:
        del continuation_scope
        return self._gateway.search_gmail_threads(
            query=query,
            page_token=page_token,
            page_size=page_size,
            include_thread_metadata=include_thread_metadata,
        )

    def list_task_lists_page(
        self,
        *,
        page_token: str | None,
        page_size: int,
    ) -> ResourcePage:
        return self._gateway.list_task_lists(page_token=page_token, page_size=page_size)

    def list_tasks_page(
        self,
        *,
        task_list_id: str,
        page_token: str | None,
        page_size: int,
        show_completed: bool,
        show_hidden: bool,
        show_deleted: bool,
        continuation_scope: tuple[str, ...],
    ) -> ResourcePage:
        del continuation_scope
        return self._gateway.list_tasks(
            task_list_id=task_list_id,
            page_token=page_token,
            page_size=page_size,
            show_completed=show_completed,
            show_hidden=show_hidden,
            show_deleted=show_deleted,
        )

    def list_calendar_events_page(
        self,
        *,
        calendar_id: str,
        page_token: str | None,
        page_size: int,
        time_min: str,
        time_max: str,
        single_events: bool,
        order_by: str,
        continuation_scope: tuple[str, ...],
    ) -> ResourcePage:
        del continuation_scope
        return self._gateway.list_calendar_events(
            calendar_id=calendar_id,
            page_token=page_token,
            page_size=page_size,
            time_min=time_min,
            time_max=time_max,
            single_events=single_events,
            order_by=order_by,
        )

    def count_gmail_page(
        self,
        *,
        query: str,
        page_token: str | None,
        page_size: int,
        include_thread_metadata: bool,
    ) -> ResourcePage:
        return self._gateway.search_gmail_threads(
            query=query,
            page_token=page_token,
            page_size=page_size,
            include_thread_metadata=include_thread_metadata,
        )

    def count_task_lists_page(
        self,
        *,
        page_token: str | None,
        page_size: int,
    ) -> ResourcePage:
        return self._gateway.list_task_lists(page_token=page_token, page_size=page_size)

    def count_tasks_page(
        self,
        *,
        task_list_id: str,
        page_token: str | None,
        page_size: int,
        show_completed: bool,
    ) -> ResourcePage:
        return self._gateway.list_tasks(
            task_list_id=task_list_id,
            page_token=page_token,
            page_size=page_size,
            show_completed=show_completed,
        )

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
    ) -> ResourcePage:
        return self._gateway.list_calendar_events(
            calendar_id=calendar_id,
            page_token=page_token,
            page_size=page_size,
            time_min=time_min,
            time_max=time_max,
            single_events=single_events,
            order_by=order_by,
        )

    def default_task_list_id(self) -> str | None:
        if self._default_tasklist_id_provider is None:
            return None
        return self._default_tasklist_id_provider()

    def default_calendar_id(self) -> str | None:
        if self._default_calendar_id_provider is None:
            return None
        return self._default_calendar_id_provider()

    def timezone_name(self) -> str:
        return self._timezone_provider()

    def current_time(self) -> datetime:
        return self._now()

    # Legacy compatibility surface. Direction is legacy -> canonical.

    def get_gmail_thread_detail(self, *, resource_id: str) -> GmailResourceDetail:
        return GetResourceHandler(self)(
            GetResourceQuery(source="gmail", resource_id=resource_id)
        ).resource

    def list_gmail_threads(
        self,
        *,
        query: str,
        page_token: str | None,
        page_size: int,
        include_thread_metadata: bool = True,
    ) -> ResourceListPage:
        return ListResourcesHandler(self)(
            ListResourcesQuery(
                source="gmail",
                query=query,
                page_token=page_token,
                page_size=page_size,
                include_thread_metadata=include_thread_metadata,
            )
        ).page

    def list_tasks(
        self,
        *,
        task_list_id: str | None,
        page_token: str | None,
        page_size: int,
        status_scope: str = "incomplete",
    ) -> ResourceListPage:
        return ListResourcesHandler(self)(
            ListResourcesQuery(
                source="tasks",
                task_list_id=task_list_id,
                page_token=page_token,
                page_size=page_size,
                status_scope=status_scope,
            )
        ).page

    def list_calendar_resources(
        self,
        *,
        calendar_id: str | None,
        time_min: str | None,
        time_max: str | None,
        page_token: str | None,
        page_size: int,
    ) -> ResourceListPage:
        return ListResourcesHandler(self)(
            ListResourcesQuery(
                source="calendar",
                calendar_id=calendar_id,
                time_min=time_min,
                time_max=time_max,
                page_token=page_token,
                page_size=page_size,
            )
        ).page

    def count_gmail_threads(self, *, query: str = "") -> ResourceCount:
        return CountResourcesHandler(self)(
            CountResourcesQuery(source="gmail", query=query)
        ).count

    def count_tasks(self, *, task_list_id: str | None) -> ResourceCount:
        return CountResourcesHandler(self)(
            CountResourcesQuery(source="tasks", task_list_id=task_list_id)
        ).count

    def count_calendar_resources(
        self,
        *,
        calendar_id: str | None,
        time_min: str | None,
        time_max: str | None,
    ) -> ResourceCount:
        return CountResourcesHandler(self)(
            CountResourcesQuery(
                source="calendar",
                calendar_id=calendar_id,
                time_min=time_min,
                time_max=time_max,
            )
        ).count
