"""List external resources through the canonical resource query boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from urllib.parse import quote
from zoneinfo import ZoneInfo

from google_work_agent.ports.connector.connector_failure import (
    ConnectorFailureCode,
    ConnectorOperationFailure,
    normalize_google_workspace_failure,
)
from google_work_agent.ports.connector.contracts.google_workspace import (
    DEFAULT_CALENDAR_ID,
    GoogleWorkspaceGatewayError,
    ResourcePage,
    ResourceSnapshot,
    ResourceType,
)

MAX_RESOURCE_PAGE_SIZE = 100
GMAIL_PRIMARY_QUERY = "in:inbox category:primary"


@dataclass(frozen=True, slots=True)
class ResourceListItem:
    source: str
    resource_type: str
    resource_id: str
    parent_id: str | None
    title: str
    subtitle: str | None
    link_url: str
    version: str
    related_resource_ids: tuple[str, ...]
    metadata: dict[str, object]
    sender_name: str | None
    sender_email: str | None
    subject: str | None
    received_at: str | None
    snippet: str | None
    has_attachments: bool


@dataclass(frozen=True, slots=True)
class ResourceListPage:
    source: str
    items: tuple[ResourceListItem, ...]
    next_page_token: str | None


class ListResourceAccess(Protocol):
    def list_gmail_page(
        self,
        *,
        query: str,
        page_token: str | None,
        page_size: int,
        include_thread_metadata: bool,
        continuation_scope: tuple[str, ...],
    ) -> ResourcePage: ...

    def list_task_lists_page(
        self,
        *,
        page_token: str | None,
        page_size: int,
    ) -> ResourcePage: ...

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
    ) -> ResourcePage: ...

    def list_tasks_materialization_page(
        self,
        *,
        task_list_id: str,
        page_token: str | None,
        page_size: int,
        show_completed: bool,
        show_hidden: bool,
        show_deleted: bool,
    ) -> ResourcePage: ...

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
    ) -> ResourcePage: ...

    def default_task_list_id(self) -> str | None: ...

    def default_calendar_id(self) -> str | None: ...

    def timezone_name(self) -> str: ...

    def current_time(self) -> datetime: ...


@dataclass(frozen=True, slots=True)
class ListResourcesQuery:
    source: str
    session_digest: str
    account_id: str
    query: str = ""
    page_token: str | None = None
    page_size: int = 20
    include_thread_metadata: bool = True
    task_list_id: str | None = None
    status_scope: str = "incomplete"
    calendar_id: str | None = None
    time_min: str | None = None
    time_max: str | None = None

    def __post_init__(self) -> None:
        if (
            len(self.session_digest) != 64
            or any(character not in "0123456789abcdef" for character in self.session_digest)
            or not self.account_id
        ):
            raise ValueError("resource continuation principal is invalid")


@dataclass(frozen=True, slots=True)
class ListResourcesResult:
    page: ResourceListPage


@dataclass(frozen=True, slots=True)
class ListResourcesHandler:
    access: ListResourceAccess

    def __call__(self, query: ListResourcesQuery) -> ListResourcesResult:
        try:
            if query.source == "gmail":
                page = self._list_gmail(query)
            elif query.source == "tasks":
                page = self._list_tasks(query)
            elif query.source == "calendar":
                page = self._list_calendar(query)
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
        return ListResourcesResult(page=page)

    def _list_gmail(self, query: ListResourcesQuery) -> ResourceListPage:
        page = self.access.list_gmail_page(
            query=query.query.strip() or GMAIL_PRIMARY_QUERY,
            page_token=query.page_token,
            page_size=_validated_page_size(query.page_size),
            include_thread_metadata=query.include_thread_metadata,
            continuation_scope=(
                query.session_digest,
                query.account_id,
                "gmail",
                query.query.strip(),
                str(query.page_size),
                "metadata" if query.include_thread_metadata else "no-metadata",
            ),
        )
        return _project_page("gmail", page)

    def _list_tasks(self, query: ListResourcesQuery) -> ResourceListPage:
        if query.status_scope not in {"incomplete", "completed"}:
            raise ValueError("invalid task status scope")
        _validated_page_size(query.page_size)
        task_list_id = query.task_list_id or self.access.default_task_list_id()
        if task_list_id is None:
            task_lists = self.access.list_task_lists_page(page_token=None, page_size=1)
            if not task_lists.items:
                return ResourceListPage(source="tasks", items=(), next_page_token=None)
            task_list_id = task_lists.items[0].resource_id

        if query.status_scope == "completed":
            if query.page_token is not None:
                raise ValueError("completed task browse is fully materialized")
            return self._materialize_completed_tasks(task_list_id=task_list_id)

        page = self.access.list_tasks_page(
            task_list_id=task_list_id,
            page_token=query.page_token,
            page_size=MAX_RESOURCE_PAGE_SIZE,
            show_completed=False,
            show_hidden=False,
            show_deleted=False,
            continuation_scope=(
                query.session_digest,
                query.account_id,
                "tasks",
                query.task_list_id or "",
                str(query.page_size),
                query.status_scope,
            ),
        )
        return _project_page("tasks", page)

    def _materialize_completed_tasks(self, *, task_list_id: str) -> ResourceListPage:
        items: list[ResourceListItem] = []
        seen_resource_ids: set[str] = set()
        provider_page_token: str | None = None

        while True:
            page = self.access.list_tasks_materialization_page(
                task_list_id=task_list_id,
                page_token=provider_page_token,
                page_size=MAX_RESOURCE_PAGE_SIZE,
                show_completed=True,
                show_hidden=True,
                show_deleted=False,
            )
            for snapshot in page.items:
                if snapshot.resource_type is not ResourceType.TASK:
                    continue
                if _task_status_projection(snapshot.payload.get("status")) != "completed":
                    continue
                if snapshot.resource_id in seen_resource_ids:
                    continue
                seen_resource_ids.add(snapshot.resource_id)
                items.append(_resource_item_from_snapshot(snapshot))

            provider_page_token = page.next_page_token
            if provider_page_token is None:
                break

        return ResourceListPage(
            source="tasks",
            items=tuple(items),
            next_page_token=None,
        )

    def _list_calendar(self, query: ListResourcesQuery) -> ResourceListPage:
        calendar_id = query.calendar_id or self.access.default_calendar_id() or DEFAULT_CALENDAR_ID
        time_min, time_max = _resolve_calendar_window(
            query.time_min,
            query.time_max,
            now=self.access.current_time(),
            timezone_name=self.access.timezone_name(),
        )
        page = self.access.list_calendar_events_page(
            calendar_id=calendar_id,
            page_token=query.page_token,
            page_size=_validated_page_size(query.page_size),
            time_min=time_min,
            time_max=time_max,
            single_events=True,
            order_by="startTime",
            continuation_scope=(
                query.session_digest,
                query.account_id,
                "calendar",
                query.calendar_id or "",
                query.time_min or "",
                query.time_max or "",
                str(query.page_size),
            ),
        )
        return _project_page("calendar", page)


def _validated_page_size(page_size: int) -> int:
    if page_size < 1:
        raise ValueError("page_size must be positive")
    return min(page_size, MAX_RESOURCE_PAGE_SIZE)


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


def _project_page(source: str, page: ResourcePage) -> ResourceListPage:
    return ResourceListPage(
        source=source,
        items=tuple(_resource_item_from_snapshot(item) for item in page.items),
        next_page_token=page.next_page_token,
    )


def _resource_item_from_snapshot(snapshot: ResourceSnapshot) -> ResourceListItem:
    title, subtitle = _display_text(snapshot)
    metadata = _metadata_from_snapshot(snapshot)
    return ResourceListItem(
        source=_source_for_type(snapshot.resource_type),
        resource_type=snapshot.resource_type.value,
        resource_id=snapshot.resource_id,
        parent_id=snapshot.parent_id,
        title=title,
        subtitle=subtitle,
        link_url=_google_link(snapshot),
        version=snapshot.version,
        related_resource_ids=tuple(snapshot.related_resource_ids),
        metadata=metadata,
        sender_name=_optional_text(metadata.get("sender_name")),
        sender_email=_optional_text(metadata.get("sender_email")),
        subject=_optional_text(metadata.get("subject")),
        received_at=_optional_text(metadata.get("received_at")),
        snippet=_optional_text(metadata.get("snippet")),
        has_attachments=bool(snapshot.payload.get("attachments")),
    )


def _source_for_type(resource_type: ResourceType) -> str:
    if resource_type in {
        ResourceType.GMAIL_THREAD,
        ResourceType.GMAIL_MESSAGE,
        ResourceType.GMAIL_DRAFT,
    }:
        return "gmail"
    if resource_type in {ResourceType.TASK_LIST, ResourceType.TASK}:
        return "tasks"
    return "calendar"


def _display_text(snapshot: ResourceSnapshot) -> tuple[str, str | None]:
    payload = snapshot.payload
    if snapshot.resource_type is ResourceType.GMAIL_THREAD:
        return _optional_text(payload.get("subject")) or "", _optional_text(payload.get("snippet"))
    if snapshot.resource_type is ResourceType.GMAIL_DRAFT:
        return str(payload.get("subject", snapshot.resource_id)), _optional_text(
            payload.get("body")
        )
    if snapshot.resource_type is ResourceType.GMAIL_MESSAGE:
        return str(payload.get("subject", snapshot.resource_id)), _optional_text(
            payload.get("snippet")
        )
    if snapshot.resource_type is ResourceType.TASK_LIST:
        return str(payload.get("title", snapshot.resource_id)), _optional_text(payload.get("notes"))
    if snapshot.resource_type is ResourceType.TASK:
        return str(payload.get("title", snapshot.resource_id)), None
    if snapshot.resource_type is ResourceType.CALENDAR:
        return str(payload.get("summary", snapshot.resource_id)), _optional_text(
            payload.get("time_zone")
        )
    if snapshot.resource_type is ResourceType.CALENDAR_EVENT:
        title = _optional_text(payload.get("title"))
        return (
            "" if title == snapshot.resource_id else title or "",
            _optional_text(payload.get("start")),
        )
    return snapshot.resource_id, None


def _metadata_from_snapshot(snapshot: ResourceSnapshot) -> dict[str, object]:
    payload = snapshot.payload
    if snapshot.resource_type is ResourceType.TASK:
        metadata: dict[str, object] = {}
        task_status = _task_status_projection(payload.get("status"))
        if task_status is not None:
            metadata["task_status"] = task_status
        scheduled_date = _scheduled_date_projection(payload.get("due"))
        if scheduled_date is not None:
            metadata["scheduled_date"] = scheduled_date
        completed_at = _optional_text(payload.get("completed"))
        if completed_at is not None:
            metadata["completed_at"] = completed_at
        return metadata
    safe_keys = {
        ResourceType.GMAIL_THREAD: (
            "participants",
            "message_ids",
            "sender_name",
            "sender_email",
            "subject",
            "received_at",
            "snippet",
            "attachments",
        ),
        ResourceType.GMAIL_MESSAGE: ("from", "to", "received_at"),
        ResourceType.GMAIL_DRAFT: ("to", "cc"),
        ResourceType.TASK_LIST: ("kind",),
        ResourceType.CALENDAR: ("time_zone",),
        ResourceType.CALENDAR_EVENT: ("start", "end", "timezone", "location"),
        ResourceType.CALENDAR_FREEBUSY: ("intervals",),
    }[snapshot.resource_type]
    return {key: value for key, value in payload.items() if key in safe_keys and value is not None}


def _task_status_projection(value: object) -> str | None:
    status = _optional_text(value)
    if status == "needsAction":
        return "incomplete"
    if status == "completed":
        return "completed"
    return None


def _scheduled_date_projection(value: object) -> str | None:
    due = _optional_text(value)
    if due is None or len(due) < 10:
        return None
    candidate = due[:10]
    try:
        datetime.fromisoformat(f"{candidate}T00:00:00")
    except ValueError:
        return None
    return candidate


def _google_link(snapshot: ResourceSnapshot) -> str:
    resource_id = quote(snapshot.resource_id, safe="")
    if snapshot.resource_type is ResourceType.GMAIL_THREAD:
        return f"https://mail.google.com/mail/u/0/#inbox/{resource_id}"
    if snapshot.resource_type is ResourceType.GMAIL_MESSAGE:
        return f"https://mail.google.com/mail/u/0/#all/{resource_id}"
    if snapshot.resource_type is ResourceType.GMAIL_DRAFT:
        return "https://mail.google.com/mail/u/0/#drafts"
    if snapshot.resource_type in {ResourceType.TASK_LIST, ResourceType.TASK}:
        return "https://tasks.google.com/embed/"
    return "https://calendar.google.com/"


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
