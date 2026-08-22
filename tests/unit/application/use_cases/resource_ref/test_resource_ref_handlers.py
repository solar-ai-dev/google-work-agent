from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime

from google_work_agent.application.resource_continuation import (
    LocalResourceContinuationStore,
    OpaqueResourceQueryService,
)
from google_work_agent.application.resource_queries import ResourceQueryService
from google_work_agent.application.use_cases.resource_ref.count_resources import (
    CountResourcesHandler,
    CountResourcesQuery,
)
from google_work_agent.application.use_cases.resource_ref.get_resource import (
    GetResourceHandler,
    GetResourceQuery,
)
from google_work_agent.application.use_cases.resource_ref.list_resources import (
    GMAIL_PRIMARY_QUERY,
    ListResourcesHandler,
    ListResourcesQuery,
)
from google_work_agent.ports import (
    GmailThreadDetail,
    ResourcePage,
    ResourceSnapshot,
    ResourceType,
)


def _snapshot(
    resource_type: ResourceType,
    resource_id: str,
    *,
    parent_id: str | None = None,
    payload: dict[str, object] | None = None,
) -> ResourceSnapshot:
    return ResourceSnapshot(
        fixture_snapshot_id=f"fixture-{resource_id}",
        resource_type=resource_type,
        resource_id=resource_id,
        parent_id=parent_id,
        related_resource_ids=((parent_id,) if parent_id is not None else ()),
        version="1",
        recovery_fingerprint=None,
        payload=payload or {},
    )


class _ResourceAccess:
    def __init__(self) -> None:
        self.gmail_calls: list[dict[str, object]] = []
        self.task_calls: list[dict[str, object]] = []
        self.calendar_calls: list[dict[str, object]] = []
        self.count_tokens: list[str | None] = []
        self.task_list_calls = 0

    def list_gmail_page(
        self,
        *,
        query: str,
        page_token: str | None,
        page_size: int,
        include_thread_metadata: bool,
        continuation_scope: tuple[str, ...],
    ) -> ResourcePage:
        self.gmail_calls.append(
            {
                "query": query,
                "page_token": page_token,
                "page_size": page_size,
                "include_thread_metadata": include_thread_metadata,
                "continuation_scope": continuation_scope,
            }
        )
        return ResourcePage(
            items=(
                _snapshot(
                    ResourceType.GMAIL_THREAD,
                    "thread/1",
                    payload={
                        "subject": "Subject",
                        "snippet": "Snippet",
                        "sender_email": "sender@example.com",
                        "unsafe": "must-not-project",
                    },
                ),
            ),
            next_page_token="local-next",
        )

    def list_task_lists_page(
        self,
        *,
        page_token: str | None,
        page_size: int,
    ) -> ResourcePage:
        self.task_list_calls += 1
        return ResourcePage(
            items=(_snapshot(ResourceType.TASK_LIST, "task-list-1"),),
            next_page_token=None,
        )

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
        self.task_calls.append(
            {
                "task_list_id": task_list_id,
                "page_token": page_token,
                "page_size": page_size,
                "show_completed": show_completed,
                "show_hidden": show_hidden,
                "show_deleted": show_deleted,
                "continuation_scope": continuation_scope,
            }
        )
        return ResourcePage(
            items=(
                _snapshot(
                    ResourceType.TASK,
                    "task-1",
                    parent_id=task_list_id,
                    payload={
                        "title": "Follow up",
                        "status": "completed",
                        "due": "2026-08-30T12:00:00+09:00",
                        "completed": "2026-08-23T10:00:00+09:00",
                        "private": "must-not-project",
                    },
                ),
            ),
            next_page_token=None,
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
        self.calendar_calls.append(
            {
                "calendar_id": calendar_id,
                "page_token": page_token,
                "page_size": page_size,
                "time_min": time_min,
                "time_max": time_max,
                "single_events": single_events,
                "order_by": order_by,
                "continuation_scope": continuation_scope,
            }
        )
        return ResourcePage(items=(), next_page_token=None)

    def count_gmail_page(
        self,
        *,
        query: str,
        page_token: str | None,
        page_size: int,
        include_thread_metadata: bool,
    ) -> ResourcePage:
        assert query == GMAIL_PRIMARY_QUERY
        assert page_size == 100
        assert include_thread_metadata is False
        self.count_tokens.append(page_token)
        if page_token is None:
            return ResourcePage(
                items=(
                    _snapshot(ResourceType.GMAIL_THREAD, "a"),
                    _snapshot(ResourceType.GMAIL_THREAD, "b"),
                ),
                next_page_token="provider-2",
            )
        assert page_token == "provider-2"
        return ResourcePage(
            items=(_snapshot(ResourceType.GMAIL_THREAD, "c"),),
            next_page_token=None,
        )

    def count_task_lists_page(
        self,
        *,
        page_token: str | None,
        page_size: int,
    ) -> ResourcePage:
        return self.list_task_lists_page(page_token=page_token, page_size=page_size)

    def count_tasks_page(
        self,
        *,
        task_list_id: str,
        page_token: str | None,
        page_size: int,
        show_completed: bool,
    ) -> ResourcePage:
        raise AssertionError("task count not expected")

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
        raise AssertionError("calendar count not expected")

    def default_task_list_id(self) -> str | None:
        return None

    def default_calendar_id(self) -> str | None:
        return None

    def timezone_name(self) -> str:
        return "Asia/Seoul"

    def current_time(self) -> datetime:
        return datetime(2026, 8, 23, 0, 0, tzinfo=UTC)

    def get_gmail_thread_detail_raw(self, *, resource_id: str) -> GmailThreadDetail:
        assert resource_id == "thread-1"
        return GmailThreadDetail(
            thread_id="thread-1",
            message_id="message-1",
            rfc822_message_id="<message-1@example.com>",
            sender_name="Sender",
            sender_email="sender@example.com",
            recipients=("user@example.com",),
            cc=(),
            subject="Subject",
            received_at="2026-08-23T09:00:00+09:00",
            body="Body",
            attachments=(),
            version="1",
        )


def test_list_resources_handler_owns_gmail_defaults_projection_and_page_validation() -> None:
    access = _ResourceAccess()

    result = ListResourcesHandler(access)(
        ListResourcesQuery(source="gmail", query="  ", page_size=500)
    )

    call = access.gmail_calls[0]
    assert call["query"] == GMAIL_PRIMARY_QUERY
    assert call["page_size"] == 100
    assert call["continuation_scope"] == ("gmail", "", "500", "metadata")
    item = result.page.items[0]
    assert result.page.next_page_token == "local-next"
    assert item.title == "Subject"
    assert item.link_url.endswith("#inbox/thread%2F1")
    assert item.metadata == {
        "sender_email": "sender@example.com",
        "subject": "Subject",
        "snippet": "Snippet",
    }


def test_list_resources_handler_owns_task_resolution_status_and_projection() -> None:
    access = _ResourceAccess()

    result = ListResourcesHandler(access)(
        ListResourcesQuery(
            source="tasks",
            task_list_id=None,
            page_size=25,
            status_scope="completed",
        )
    )

    assert access.task_list_calls == 1
    call = access.task_calls[0]
    assert call == {
        "task_list_id": "task-list-1",
        "page_token": None,
        "page_size": 100,
        "show_completed": True,
        "show_hidden": True,
        "show_deleted": False,
        "continuation_scope": ("tasks", "", "25", "completed"),
    }
    item = result.page.items[0]
    assert item.metadata == {
        "task_status": "completed",
        "scheduled_date": "2026-08-30",
        "completed_at": "2026-08-23T10:00:00+09:00",
    }


def test_list_resources_handler_owns_calendar_defaults_and_90_day_window() -> None:
    access = _ResourceAccess()

    ListResourcesHandler(access)(ListResourcesQuery(source="calendar", page_size=20))

    call = access.calendar_calls[0]
    assert call["calendar_id"] == "primary"
    assert call["single_events"] is True
    assert call["order_by"] == "startTime"
    assert call["continuation_scope"] == ("calendar", "", "", "", "20")
    assert call["time_min"] == "2026-08-23T09:00:00+09:00"
    assert call["time_max"] == "2026-11-21T09:00:00+09:00"


def test_count_resources_handler_owns_multi_page_count_without_api_continuations() -> None:
    access = _ResourceAccess()

    result = CountResourcesHandler(access)(CountResourcesQuery(source="gmail"))

    assert result.count.total_count == 3
    assert access.count_tokens == [None, "provider-2"]


def test_get_resource_handler_owns_detail_projection_and_canonical_link() -> None:
    access = _ResourceAccess()

    result = GetResourceHandler(access)(
        GetResourceQuery(source="gmail", resource_id="thread-1")
    )

    assert result.resource.resource_id == "thread-1"
    assert result.resource.message_id == "message-1"
    assert result.resource.canonical_url.endswith(
        "#search/rfc822msgid%3A%3Cmessage-1%40example.com%3E"
    )


class _PagingGateway:
    def __init__(self) -> None:
        self.tokens: list[str | None] = []

    def search_gmail_threads(
        self,
        *,
        query: str,
        page_token: str | None,
        page_size: int,
        include_thread_metadata: bool = True,
    ) -> ResourcePage:
        self.tokens.append(page_token)
        return ResourcePage(
            items=(),
            next_page_token="provider-next" if page_token is None else None,
        )


def _token_factory(values: Iterator[str]) -> Callable[[], str]:
    return lambda: next(values)


def test_canonical_list_handler_preserves_opaque_provider_token_boundary() -> None:
    gateway = _PagingGateway()
    raw = ResourceQueryService(gateway=gateway)
    opaque = OpaqueResourceQueryService(
        raw,
        continuation_store=LocalResourceContinuationStore(
            token_factory=_token_factory(iter(("local-next",)))
        ),
    )
    handler = ListResourcesHandler(opaque)

    first = handler(ListResourcesQuery(source="gmail", query="", page_size=20)).page
    assert first.next_page_token == "local-next"
    assert first.next_page_token != "provider-next"

    second = handler(
        ListResourcesQuery(
            source="gmail",
            query="",
            page_token=first.next_page_token,
            page_size=20,
        )
    ).page
    assert second.next_page_token is None
    assert gateway.tokens == [None, "provider-next"]


def test_canonical_count_handler_never_allocates_api_continuation_handles() -> None:
    gateway = _PagingGateway()
    raw = ResourceQueryService(gateway=gateway)
    opaque = OpaqueResourceQueryService(
        raw,
        continuation_store=LocalResourceContinuationStore(
            token_factory=lambda: (_ for _ in ()).throw(
                AssertionError("count allocated an API continuation")
            )
        ),
    )

    result = CountResourcesHandler(opaque)(CountResourcesQuery(source="gmail"))

    assert result.count.total_count == 0
    assert gateway.tokens == [None, "provider-next"]
