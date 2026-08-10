"""Read-only Google resource query services for UI projections."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

from google_work_agent.ports import (
    GoogleWorkspaceGateway,
    ResourceSnapshot,
    ResourceType,
)

MAX_RESOURCE_PAGE_SIZE = 50


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


class ResourceQueryService:
    """UI-facing Google Workspace queries over the gateway."""

    def __init__(self, *, gateway: GoogleWorkspaceGateway) -> None:
        self._gateway = gateway

    def list_gmail_threads(
        self,
        *,
        query: str,
        page_token: str | None,
        page_size: int,
    ) -> ResourceListPage:
        page = self._gateway.search_gmail_threads(
            query=query,
            page_token=page_token,
            page_size=_validated_page_size(page_size),
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
    ) -> ResourceListPage:
        if task_list_id is None:
            page = self._gateway.list_task_lists(
                page_token=page_token,
                page_size=_validated_page_size(page_size),
            )
        else:
            page = self._gateway.list_tasks(
                task_list_id=task_list_id,
                page_token=page_token,
                page_size=_validated_page_size(page_size),
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
        page_token: str | None,
        page_size: int,
    ) -> ResourceListPage:
        if calendar_id is None:
            page = self._gateway.list_calendars(
                page_token=page_token,
                page_size=_validated_page_size(page_size),
            )
        else:
            page = self._gateway.list_calendar_events(
                calendar_id=calendar_id,
                page_token=page_token,
                page_size=_validated_page_size(page_size),
            )
        return ResourceListPage(
            source="calendar",
            items=tuple(_resource_item_from_snapshot(item) for item in page.items),
            next_page_token=page.next_page_token,
        )


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
        return str(payload.get("title", snapshot.resource_id)), _optional_text(
            payload.get("status")
        )
    if snapshot.resource_type is ResourceType.CALENDAR:
        return str(payload.get("summary", snapshot.resource_id)), _optional_text(
            payload.get("time_zone")
        )
    if snapshot.resource_type is ResourceType.CALENDAR_EVENT:
        return str(payload.get("title", snapshot.resource_id)), _optional_text(payload.get("start"))
    return snapshot.resource_id, None


def _metadata_from_snapshot(snapshot: ResourceSnapshot) -> dict[str, object]:
    payload = snapshot.payload
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
        ResourceType.TASK: ("due", "status"),
        ResourceType.CALENDAR: ("time_zone",),
        ResourceType.CALENDAR_EVENT: ("start", "end"),
        ResourceType.CALENDAR_FREEBUSY: ("intervals",),
    }[snapshot.resource_type]
    return {key: value for key, value in payload.items() if key in safe_keys and value is not None}


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
