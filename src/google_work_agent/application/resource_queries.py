"""Read-only Google resource query services for UI projections."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo

from google_work_agent.ports import (
    GmailAttachmentMetadata,
    GmailUiReadGateway,
    GoogleWorkspaceGateway,
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


@dataclass(frozen=True, slots=True)
class ResourceListPage:
    source: str
    items: tuple[ResourceListItem, ...]
    next_page_token: str | None


@dataclass(frozen=True, slots=True)
class ResourceCount:
    source: str
    total_count: int


@dataclass(frozen=True, slots=True)
class GmailResourceDetail:
    resource_id: str
    message_id: str
    sender_name: str | None
    sender_email: str | None
    recipients: tuple[str, ...]
    cc: tuple[str, ...]
    subject: str | None
    received_at: str | None
    body: str | None
    attachments: tuple[GmailAttachmentMetadata, ...]
    canonical_url: str


class ResourceQueryService:
    """UI-facing Google Workspace queries over the gateway."""

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

    def get_gmail_thread_detail(self, *, resource_id: str) -> GmailResourceDetail:
        if self._gmail_detail_gateway is None:
            raise RuntimeError("Gmail detail provider is not configured")
        detail = self._gmail_detail_gateway.get_thread_detail(thread_id=resource_id)
        return GmailResourceDetail(
            resource_id=detail.thread_id,
            message_id=detail.message_id,
            sender_name=detail.sender_name,
            sender_email=detail.sender_email,
            recipients=detail.recipients,
            cc=detail.cc,
            subject=detail.subject,
            received_at=detail.received_at,
            body=detail.body,
            attachments=detail.attachments,
            canonical_url=_gmail_search_permalink(detail.rfc822_message_id),
        )

    def list_gmail_threads(
        self,
        *,
        query: str,
        page_token: str | None,
        page_size: int,
        include_thread_metadata: bool = True,
    ) -> ResourceListPage:
        page = self._gateway.search_gmail_threads(
            query=query.strip() or GMAIL_PRIMARY_QUERY,
            page_token=page_token,
            page_size=_validated_page_size(page_size),
            include_thread_metadata=include_thread_metadata,
        )
        return ResourceListPage(
            source="gmail",
            items=tuple(_resource_item_from_snapshot(item) for item in page.items),
            next_page_token=page.next_page_token,
        )

    def list_tasks(
        self,
        *,
        task_list_id: str | None,
        page_token: str | None,
        page_size: int,
        status_scope: str = "incomplete",
    ) -> ResourceListPage:
        if status_scope not in {"incomplete", "completed"}:
            raise ValueError("invalid task status scope")
        resolved_task_list_id = self._resolve_task_list_id(task_list_id)
        if resolved_task_list_id is None:
            return ResourceListPage(source="tasks", items=(), next_page_token=None)
        _validated_page_size(page_size)
        page = self._gateway.list_tasks(
            task_list_id=resolved_task_list_id,
            page_token=page_token,
            page_size=MAX_RESOURCE_PAGE_SIZE,
            show_completed=status_scope == "completed",
            show_hidden=status_scope == "completed",
            show_deleted=False,
        )
        return ResourceListPage(
            source="tasks",
            items=tuple(_resource_item_from_snapshot(item) for item in page.items),
            next_page_token=page.next_page_token,
        )

    def list_calendar_resources(
        self,
        *,
        calendar_id: str | None,
        time_min: str | None,
        time_max: str | None,
        page_token: str | None,
        page_size: int,
    ) -> ResourceListPage:
        configured_calendar_id = (
            self._default_calendar_id_provider() if self._default_calendar_id_provider else None
        )
        resolved_calendar_id = calendar_id or configured_calendar_id or "primary"
        resolved_time_min, resolved_time_max = self._resolve_calendar_window(time_min, time_max)
        page = self._gateway.list_calendar_events(
            calendar_id=resolved_calendar_id,
            page_token=page_token,
            page_size=_validated_page_size(page_size),
            time_min=resolved_time_min,
            time_max=resolved_time_max,
            single_events=True,
            order_by="startTime",
        )
        return ResourceListPage(
            source="calendar",
            items=tuple(_resource_item_from_snapshot(item) for item in page.items),
            next_page_token=page.next_page_token,
        )

    def count_gmail_threads(self, *, query: str = "") -> ResourceCount:
        return ResourceCount(
            source="gmail",
            total_count=self._count_pages(
                lambda page_token: self._gateway.search_gmail_threads(
                    query=query.strip() or GMAIL_PRIMARY_QUERY,
                    page_token=page_token,
                    page_size=MAX_RESOURCE_PAGE_SIZE,
                    include_thread_metadata=False,
                )
            ),
        )

    def count_tasks(self, *, task_list_id: str | None) -> ResourceCount:
        resolved_task_list_id = self._resolve_task_list_id(task_list_id)
        if resolved_task_list_id is None:
            return ResourceCount(source="tasks", total_count=0)
        return ResourceCount(
            source="tasks",
            total_count=self._count_pages(
                lambda page_token: self._gateway.list_tasks(
                    task_list_id=resolved_task_list_id,
                    page_token=page_token,
                    page_size=MAX_RESOURCE_PAGE_SIZE,
                    show_completed=False,
                )
            ),
        )

    def count_calendar_resources(
        self,
        *,
        calendar_id: str | None,
        time_min: str | None,
        time_max: str | None,
    ) -> ResourceCount:
        configured_calendar_id = (
            self._default_calendar_id_provider() if self._default_calendar_id_provider else None
        )
        resolved_calendar_id = calendar_id or configured_calendar_id or "primary"
        resolved_time_min, resolved_time_max = self._resolve_calendar_window(time_min, time_max)
        return ResourceCount(
            source="calendar",
            total_count=self._count_pages(
                lambda page_token: self._gateway.list_calendar_events(
                    calendar_id=resolved_calendar_id,
                    page_token=page_token,
                    page_size=MAX_RESOURCE_PAGE_SIZE,
                    time_min=resolved_time_min,
                    time_max=resolved_time_max,
                    single_events=True,
                    order_by="startTime",
                )
            ),
        )

    def _resolve_task_list_id(self, task_list_id: str | None) -> str | None:
        configured_task_list_id = (
            self._default_tasklist_id_provider() if self._default_tasklist_id_provider else None
        )
        resolved_task_list_id = task_list_id or configured_task_list_id
        if resolved_task_list_id is not None:
            return resolved_task_list_id
        task_lists = self._gateway.list_task_lists(page_token=None, page_size=1)
        return task_lists.items[0].resource_id if task_lists.items else None

    def _resolve_calendar_window(
        self, time_min: str | None, time_max: str | None
    ) -> tuple[str, str]:
        if (time_min is None) != (time_max is None):
            raise ValueError("time_min and time_max must be provided together")
        if time_min is not None and time_max is not None:
            return time_min, time_max
        window_start = self._now().astimezone(ZoneInfo(self._timezone_provider()))
        return (
            window_start.isoformat(timespec="seconds"),
            (window_start + timedelta(days=90)).isoformat(timespec="seconds"),
        )

    @staticmethod
    def _count_pages(fetch_page: Callable[[str | None], ResourcePage]) -> int:
        page_token: str | None = None
        total_count = 0
        while True:
            page = fetch_page(page_token)
            total_count += len(page.items)
            page_token = page.next_page_token
            if page_token is None:
                return total_count


def _validated_page_size(page_size: int) -> int:
    if page_size < 1:
        raise ValueError("page_size must be positive")
    return min(page_size, MAX_RESOURCE_PAGE_SIZE)


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
        ),
        ResourceType.GMAIL_MESSAGE: ("from", "to", "received_at"),
        ResourceType.GMAIL_DRAFT: ("to", "cc"),
        ResourceType.TASK_LIST: ("kind",),
        ResourceType.CALENDAR: ("time_zone",),
        ResourceType.CALENDAR_EVENT: ("start", "end"),
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


def _gmail_search_permalink(rfc822_message_id: str | None) -> str:
    # #inbox/{thread_id} and #all/{message_id} were both verified to fail on
    # a cold click (label-scoped / session-scoped Gmail Web internals). A
    # rfc822msgid: search against the message's own RFC822 Message-ID header
    # was verified to resolve the exact message every time, regardless of
    # label or session state.
    if not rfc822_message_id:
        # Not #all/{message_id} (a direct-open attempt, already verified to
        # fail on a cold click) -- just the All Mail list view, with no id.
        return "https://mail.google.com/mail/u/0/#all"
    query = quote(f"rfc822msgid:{rfc822_message_id}", safe="")
    return f"https://mail.google.com/mail/u/0/#search/{query}"


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
