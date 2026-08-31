from __future__ import annotations

from datetime import UTC, datetime

import pytest

from google_work_agent.application.use_cases.resource.connector_resource_access import (
    ConnectorResourceAccess as _ConnectorResourceAccess,
)
from google_work_agent.application.use_cases.resource.get_resource_count import (
    GetResourceCountHandler,
    GetResourceCountQuery,
    ResourceCount,
)
from google_work_agent.application.use_cases.resource.get_resource_detail import (
    GetResourceDetailHandler,
    GetResourceDetailQuery,
    GmailResourceDetail,
    _gmail_search_permalink,
)
from google_work_agent.application.use_cases.resource.list_resources import (
    ListResourcesHandler,
    ListResourcesQuery,
    ResourceListPage,
)
from google_work_agent.ports.connector.contracts.google_workspace import (
    ResourcePage,
    ResourceSnapshot,
    ResourceType,
)


class ConnectorResourceAccess(_ConnectorResourceAccess):
    """Test-only convenience surface that calls the exact canonical handlers."""

    def get_gmail_thread_detail(self, *, resource_id: str) -> GmailResourceDetail:
        return GetResourceDetailHandler(self)(
            GetResourceDetailQuery(source="gmail", resource_id=resource_id)
        ).resource

    def list_gmail_threads(self, **kwargs: object) -> ResourceListPage:
        return ListResourcesHandler(self)(
            ListResourcesQuery(
                source="gmail", session_digest="a" * 64, account_id="account-1", **kwargs
            )  # type: ignore[arg-type]
        ).page

    def list_tasks(self, **kwargs: object) -> ResourceListPage:
        return ListResourcesHandler(self)(
            ListResourcesQuery(
                source="tasks", session_digest="a" * 64, account_id="account-1", **kwargs
            )  # type: ignore[arg-type]
        ).page

    def list_calendar_resources(self, **kwargs: object) -> ResourceListPage:
        return ListResourcesHandler(self)(
            ListResourcesQuery(
                source="calendar", session_digest="a" * 64, account_id="account-1", **kwargs
            )  # type: ignore[arg-type]
        ).page

    def count_gmail_threads(self, *, query: str = "") -> ResourceCount:
        return GetResourceCountHandler(self)(
            GetResourceCountQuery(source="gmail", query=query)
        ).count

    def count_tasks(self, *, task_list_id: str | None) -> ResourceCount:
        return GetResourceCountHandler(self)(
            GetResourceCountQuery(source="tasks", task_list_id=task_list_id)
        ).count

    def count_calendar_resources(
        self,
        *,
        calendar_id: str | None,
        time_min: str | None,
        time_max: str | None,
    ) -> ResourceCount:
        return GetResourceCountHandler(self)(
            GetResourceCountQuery(
                source="calendar",
                calendar_id=calendar_id,
                time_min=time_min,
                time_max=time_max,
            )
        ).count


class _Gateway:
    def __init__(self, snapshot: ResourceSnapshot) -> None:
        self.snapshot = snapshot
        self.include_thread_metadata: bool | None = None

    def search_gmail_threads(
        self,
        *,
        query: str,
        page_token: str | None,
        page_size: int,
        include_thread_metadata: bool = True,
    ) -> ResourcePage:
        self.include_thread_metadata = include_thread_metadata
        assert query == "project"
        assert page_token == "page-1"
        assert page_size == 10
        return ResourcePage(items=(self.snapshot,), next_page_token="page-2")

    def get_gmail_thread(self, *, thread_id: str) -> ResourceSnapshot:
        assert thread_id == self.snapshot.resource_id
        return self.snapshot

    def list_tasks(
        self,
        *,
        task_list_id: str,
        page_token: str | None,
        page_size: int,
        show_completed: bool = False,
        show_hidden: bool = False,
        show_deleted: bool = False,
    ) -> ResourcePage:
        return ResourcePage(items=(self.snapshot,), next_page_token=None)


class _CalendarGateway:
    def __init__(self, *, event_title: str = "Project review") -> None:
        self.arguments: dict[str, object] | None = None
        self.event_title = event_title

    def list_calendars(self, *, page_token: str | None, page_size: int) -> ResourcePage:
        raise AssertionError("Calendar Sidebar must not list calendar containers")

    def list_calendar_events(
        self,
        *,
        calendar_id: str,
        page_token: str | None,
        page_size: int,
        time_min: str | None = None,
        time_max: str | None = None,
        single_events: bool = False,
        order_by: str | None = None,
    ) -> ResourcePage:
        self.arguments = {
            "calendar_id": calendar_id,
            "page_token": page_token,
            "page_size": page_size,
            "time_min": time_min,
            "time_max": time_max,
            "single_events": single_events,
            "order_by": order_by,
        }
        return ResourcePage(
            items=(
                ResourceSnapshot(
                    fixture_snapshot_id="event-1",
                    resource_type=ResourceType.CALENDAR_EVENT,
                    resource_id="event-1",
                    parent_id=calendar_id,
                    related_resource_ids=(calendar_id,),
                    version="1",
                    recovery_fingerprint=None,
                    payload={
                        "title": self.event_title,
                        "start": "2026-08-10T09:00:00+09:00",
                        "end": "2026-08-10T10:00:00+09:00",
                    },
                ),
            ),
            next_page_token="next-events",
        )


class _TaskGateway:
    def __init__(self, *, task_payload: dict[str, object] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.task_payload = task_payload

    def list_task_lists(self, *, page_token: str | None, page_size: int) -> ResourcePage:
        self.calls.append(("list_task_lists", {"page_token": page_token, "page_size": page_size}))
        return ResourcePage(
            items=(
                ResourceSnapshot(
                    fixture_snapshot_id="task-list-default",
                    resource_type=ResourceType.TASK_LIST,
                    resource_id="task-list-default",
                    parent_id=None,
                    related_resource_ids=(),
                    version="1",
                    recovery_fingerprint=None,
                    payload={"title": "내 작업"},
                ),
            ),
            next_page_token=None,
        )

    def list_tasks(
        self,
        *,
        task_list_id: str,
        page_token: str | None,
        page_size: int,
        show_completed: bool = False,
        show_hidden: bool = False,
        show_deleted: bool = False,
    ) -> ResourcePage:
        self.calls.append(
            (
                "list_tasks",
                {
                    "task_list_id": task_list_id,
                    "page_token": page_token,
                    "page_size": page_size,
                    "show_completed": show_completed,
                },
            )
        )
        return ResourcePage(
            items=(
                ResourceSnapshot(
                    fixture_snapshot_id="task-1",
                    resource_type=ResourceType.TASK,
                    resource_id="task-1",
                    parent_id=task_list_id,
                    related_resource_ids=(task_list_id,),
                    version="1",
                    recovery_fingerprint=None,
                    payload=self.task_payload
                    or {
                        "title": "후속 조치",
                        "due": "2026-08-12T09:00:00+09:00",
                        "status": "needsAction",
                        "priority": "높음",
                    },
                ),
            ),
            next_page_token=None,
        )


def test_gmail_list_projection_exposes_metadata_for_frontend() -> None:
    snapshot = _snapshot(
        payload={
            "sender_name": "Kim Daeri",
            "sender_email": "kim.daeri@example.com",
            "subject": "Q2 campaign follow-up",
            "received_at": "Sat, 24 May 2025 09:15:00 +0900",
            "snippet": "Please review the campaign result.",
        }
    )
    service = ConnectorResourceAccess(gateway=_Gateway(snapshot))

    page = service.list_gmail_threads(query="project", page_token="page-1", page_size=10)

    item = page.items[0]
    assert page.next_page_token == "page-2"
    assert item.resource_id == "thread-1"
    assert item.title == "Q2 campaign follow-up"
    assert item.subtitle == "Please review the campaign result."
    assert item.sender_name == "Kim Daeri"
    assert item.sender_email == "kim.daeri@example.com"
    assert item.subject == "Q2 campaign follow-up"
    assert item.received_at == "Sat, 24 May 2025 09:15:00 +0900"
    assert item.snippet == "Please review the campaign result."
    assert item.metadata == {
        "sender_name": "Kim Daeri",
        "sender_email": "kim.daeri@example.com",
        "subject": "Q2 campaign follow-up",
        "received_at": "Sat, 24 May 2025 09:15:00 +0900",
        "snippet": "Please review the campaign result.",
    }


def test_gmail_list_projection_forwards_lightweight_metadata_option() -> None:
    gateway = _Gateway(_snapshot(payload={}))
    service = ConnectorResourceAccess(gateway=gateway)

    service.list_gmail_threads(
        query="project",
        page_token="page-1",
        page_size=10,
        include_thread_metadata=False,
    )

    assert gateway.include_thread_metadata is False


def test_gmail_list_projection_does_not_use_resource_id_as_title_fallback() -> None:
    service = ConnectorResourceAccess(gateway=_Gateway(_snapshot(payload={})))

    item = service.list_gmail_threads(query="project", page_token="page-1", page_size=10).items[0]

    assert item.resource_id == "thread-1"
    assert item.title == ""
    assert item.subject is None
    assert item.metadata == {}


def test_gmail_detail_projection_is_ui_only_and_preserves_thread_identity() -> None:
    service = ConnectorResourceAccess(
        gateway=_Gateway(
            _snapshot(
                payload={
                    "message_id": "message-2",
                    "rfc822_message_id": "<message-2@example.com>",
                    "sender_name": "Kim Daeri",
                    "sender_email": "kim.daeri@example.com",
                    "recipients": ["user@example.com"],
                    "cc": ["team@example.com"],
                    "subject": "Q2 campaign follow-up",
                    "received_at": "Mon, 10 Aug 2026 09:15:00 +0900",
                    "body": "Actual message body",
                    "attachments": [
                        {
                            "message_id": "message-2",
                            "attachment_id": "attachment-1",
                            "filename": "report.pdf",
                            "mime_type": "application/pdf",
                            "size_bytes": 2048,
                        }
                    ],
                }
            )
        ),
    )

    detail = service.get_gmail_thread_detail(resource_id="thread-1")

    assert detail.resource_id == "thread-1"
    assert detail.message_id == "message-2"
    assert detail.sender_name == "Kim Daeri"
    assert detail.recipients == ("user@example.com",)
    assert detail.body == "Actual message body"
    # rfc822msgid: search was verified to resolve the exact message
    # regardless of Gmail label/session state, unlike #inbox/{thread_id} or
    # #all/{message_id}, which were both verified to fail on a cold click.
    assert detail.canonical_url == (
        "https://mail.google.com/mail/u/0/#search/rfc822msgid%3A%3Cmessage-2%40example.com%3E"
    )
    assert detail.attachments[0].attachment_id == "attachment-1"


def test_gmail_search_permalink_falls_back_to_all_mail_when_rfc822_message_id_is_missing() -> None:
    assert _gmail_search_permalink(None) == "https://mail.google.com/mail/u/0/#all"


def test_tasks_sidebar_uses_configured_default_task_list_for_actual_tasks() -> None:
    gateway = _TaskGateway()
    service = ConnectorResourceAccess(
        gateway=gateway,
        default_tasklist_id_provider=lambda: "configured-task-list",
    )

    page = service.list_tasks(task_list_id=None, page_token=None, page_size=10)

    assert gateway.calls == [
        (
            "list_tasks",
            {
                "task_list_id": "configured-task-list",
                "page_token": None,
                "page_size": 100,
                "show_completed": False,
            },
        )
    ]
    assert page.next_page_token is None
    assert page.items[0].resource_type == "task"
    assert page.items[0].title == "후속 조치"
    assert page.items[0].metadata == {
        "scheduled_date": "2026-08-12",
        "task_status": "incomplete",
    }


def test_task_projection_keeps_provider_calendar_date_without_timezone_conversion() -> None:
    snapshot = ResourceSnapshot(
        fixture_snapshot_id="task-completed",
        resource_type=ResourceType.TASK,
        resource_id="task-completed",
        parent_id="task-list-default",
        related_resource_ids=("task-list-default",),
        version="1",
        recovery_fingerprint=None,
        payload={
            "title": "완료 작업",
            "due": "2026-08-11T00:00:00.000Z",
            "status": "completed",
            "completed": "2026-08-13T00:30:00.000Z",
        },
    )
    service = ConnectorResourceAccess(gateway=_Gateway(snapshot))

    item = service.list_tasks(
        task_list_id="task-list-default", page_token=None, page_size=10
    ).items[0]

    assert item.title == "완료 작업"
    assert item.metadata == {
        "task_status": "completed",
        "scheduled_date": "2026-08-11",
        "completed_at": "2026-08-13T00:30:00.000Z",
    }


def test_task_projection_preserves_a_provider_title() -> None:
    gateway = _TaskGateway(
        task_payload={
            "title": "GWA-DEADLINE-ONLY-TEST",
            "due": "2026-08-12T00:00:00.000Z",
            "status": "needsAction",
        }
    )
    service = ConnectorResourceAccess(gateway=gateway)

    item = service.list_tasks(
        task_list_id="task-list-default", page_token=None, page_size=100
    ).items[0]

    assert item.resource_id == "task-1"
    assert item.title == "GWA-DEADLINE-ONLY-TEST"
    assert item.metadata == {"task_status": "incomplete", "scheduled_date": "2026-08-12"}


def test_tasks_sidebar_resolves_first_actual_task_list_before_listing_tasks() -> None:
    gateway = _TaskGateway()
    service = ConnectorResourceAccess(gateway=gateway, default_tasklist_id_provider=lambda: None)

    page = service.list_tasks(task_list_id=None, page_token=None, page_size=10)

    assert gateway.calls == [
        ("list_task_lists", {"page_token": None, "page_size": 1}),
        (
            "list_tasks",
            {
                "task_list_id": "task-list-default",
                "page_token": None,
                "page_size": 100,
                "show_completed": False,
            },
        ),
    ]
    assert page.items[0].resource_type == "task"


def test_calendar_sidebar_queries_upcoming_events_from_configured_default_calendar() -> None:
    gateway = _CalendarGateway()
    service = ConnectorResourceAccess(
        gateway=gateway,
        default_calendar_id_provider=lambda: "work-calendar",
        now=lambda: datetime(2026, 8, 10, 0, 0, tzinfo=UTC),
    )

    page = service.list_calendar_resources(
        calendar_id=None,
        time_min=None,
        time_max=None,
        page_token="events-page-1",
        page_size=10,
    )

    assert gateway.arguments == {
        "calendar_id": "work-calendar",
        "page_token": "events-page-1",
        "page_size": 10,
        "time_min": "2026-08-10T00:00:00+00:00",
        "time_max": "2026-11-08T00:00:00+00:00",
        "single_events": True,
        "order_by": "startTime",
    }
    assert page.next_page_token == "next-events"
    assert page.items[0].resource_type == "calendar_event"
    assert page.items[0].title == "Project review"
    assert page.items[0].metadata == {
        "start": "2026-08-10T09:00:00+09:00",
        "end": "2026-08-10T10:00:00+09:00",
    }


def test_calendar_sidebar_uses_primary_when_default_calendar_is_not_configured() -> None:
    gateway = _CalendarGateway()
    service = ConnectorResourceAccess(
        gateway=gateway,
        default_calendar_id_provider=lambda: None,
        now=lambda: datetime(2026, 8, 10, 0, 0, tzinfo=UTC),
    )

    service.list_calendar_resources(
        calendar_id=None,
        time_min="2026-08-10T01:00:00Z",
        time_max="2026-11-08T01:00:00Z",
        page_token=None,
        page_size=10,
    )

    assert gateway.arguments is not None
    assert gateway.arguments["calendar_id"] == "primary"
    assert gateway.arguments["time_min"] == "2026-08-10T01:00:00Z"


def test_calendar_ui_projection_hides_snapshot_id_title_fallback() -> None:
    gateway = _CalendarGateway(event_title="event-1")
    service = ConnectorResourceAccess(
        gateway=gateway,
        now=lambda: datetime(2026, 8, 10, 0, 0, tzinfo=UTC),
    )

    page = service.list_calendar_resources(
        calendar_id="primary",
        time_min="2026-08-10T01:00:00Z",
        time_max="2026-11-08T01:00:00Z",
        page_token=None,
        page_size=10,
    )

    assert page.items[0].resource_id == "event-1"
    assert page.items[0].title == ""


def test_exact_counts_traverse_all_pages_with_source_scopes() -> None:
    snapshot = _snapshot(payload={})

    class Gateway:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def search_gmail_threads(self, **kwargs: object) -> ResourcePage:
            self.calls.append(("gmail", kwargs))
            return ResourcePage(items=(snapshot,), next_page_token=None)

        def list_tasks(self, **kwargs: object) -> ResourcePage:
            self.calls.append(("tasks", kwargs))
            return ResourcePage(items=(snapshot, snapshot), next_page_token=None)

        def list_calendar_events(self, **kwargs: object) -> ResourcePage:
            self.calls.append(("calendar", kwargs))
            return ResourcePage(items=(snapshot, snapshot, snapshot), next_page_token=None)

    gateway = Gateway()
    service = ConnectorResourceAccess(
        gateway=gateway,  # type: ignore[arg-type]
        default_tasklist_id_provider=lambda: "task-list-default",
        now=lambda: datetime(2026, 8, 10, 0, 0, tzinfo=UTC),
    )

    assert service.count_gmail_threads().total_count == 1
    assert service.count_tasks(task_list_id=None).total_count == 2
    assert (
        service.count_calendar_resources(
            calendar_id="primary",
            time_min="2026-08-10T00:00:00Z",
            time_max="2026-11-08T00:00:00Z",
        ).total_count
        == 3
    )
    assert gateway.calls == [
        (
            "gmail",
            {
                "query": "in:inbox category:primary",
                "page_token": None,
                "page_size": 100,
                "include_thread_metadata": False,
            },
        ),
        (
            "tasks",
            {
                "task_list_id": "task-list-default",
                "page_token": None,
                "page_size": 100,
                "show_completed": False,
            },
        ),
        (
            "calendar",
            {
                "calendar_id": "primary",
                "page_token": None,
                "page_size": 100,
                "time_min": "2026-08-10T00:00:00Z",
                "time_max": "2026-11-08T00:00:00Z",
                "single_events": True,
                "order_by": "startTime",
            },
        ),
    ]


def test_gmail_count_traverses_all_provider_pages() -> None:
    snapshot = _snapshot(payload={"snippet": "메일"})

    class Gateway:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def search_gmail_threads(self, **kwargs: object) -> ResourcePage:
            self.calls.append(kwargs)
            page_token = kwargs["page_token"]
            if page_token is None:
                return ResourcePage(items=(snapshot,) * 100, next_page_token="page-2")
            if page_token == "page-2":
                return ResourcePage(items=(snapshot,) * 100, next_page_token="page-3")
            return ResourcePage(items=(snapshot,) * 37, next_page_token=None)

    gateway = Gateway()
    service = ConnectorResourceAccess(gateway=gateway)  # type: ignore[arg-type]

    assert service.count_gmail_threads(query="from:kim@example.com").total_count == 237
    assert gateway.calls == [
        {
            "query": "from:kim@example.com",
            "page_token": None,
            "page_size": 100,
            "include_thread_metadata": False,
        },
        {
            "query": "from:kim@example.com",
            "page_token": "page-2",
            "page_size": 100,
            "include_thread_metadata": False,
        },
        {
            "query": "from:kim@example.com",
            "page_token": "page-3",
            "page_size": 100,
            "include_thread_metadata": False,
        },
    ]


def test_count_does_not_return_partial_total_when_a_later_page_fails() -> None:
    snapshot = _snapshot(payload={"snippet": "메일"})

    class Gateway:
        def search_gmail_threads(self, **kwargs: object) -> ResourcePage:
            if kwargs["page_token"] is None:
                return ResourcePage(items=(snapshot,), next_page_token="next")
            raise RuntimeError("provider unavailable")

    service = ConnectorResourceAccess(gateway=Gateway())  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="provider unavailable"):
        service.count_gmail_threads()


class _PagedTaskGateway:
    def __init__(self, pages: dict[str | None, ResourcePage]) -> None:
        self.pages = pages
        self.calls: list[dict[str, object]] = []

    def list_tasks(self, **kwargs: object) -> ResourcePage:
        self.calls.append(kwargs)
        return self.pages[kwargs["page_token"] if isinstance(kwargs["page_token"], str) else None]


def _task(index: int, due: str | None) -> ResourceSnapshot:
    return ResourceSnapshot(
        fixture_snapshot_id=f"task-{index}",
        resource_type=ResourceType.TASK,
        resource_id=f"task-{index}",
        parent_id="list",
        related_resource_ids=("list",),
        version="1",
        recovery_fingerprint=None,
        payload={"title": f"Task {index}", "due": due, "status": "needsAction"},
    )


def test_tasks_completed_scope_forwards_all_provider_visibility_flags() -> None:
    task = ResourceSnapshot(
        fixture_snapshot_id="done-1",
        resource_type=ResourceType.TASK,
        resource_id="done-1",
        parent_id="list",
        related_resource_ids=("list",),
        version="1",
        recovery_fingerprint=None,
        payload={"title": "완료 업무", "status": "completed"},
    )
    gateway = _PagedTaskGateway({None: ResourcePage(items=(task,), next_page_token=None)})
    service = ConnectorResourceAccess(gateway=gateway)

    page = service.list_tasks(
        task_list_id="list", page_token=None, page_size=100, status_scope="completed"
    )

    assert page.items[0].metadata["task_status"] == "completed"
    assert gateway.calls == [
        {
            "task_list_id": "list",
            "page_token": None,
            "page_size": 100,
            "show_completed": True,
            "show_hidden": True,
            "show_deleted": False,
        }
    ]


def test_tasks_browse_keeps_provider_order_and_does_not_traverse_past_first_batch() -> None:
    tasks = tuple(
        _task(index, f"2026-08-{(100 - index) % 28 + 1:02d}T00:00:00Z") for index in range(100)
    )
    gateway = _PagedTaskGateway({None: ResourcePage(tasks, "provider-page-2")})

    page = ConnectorResourceAccess(gateway=gateway).list_tasks(
        task_list_id="list", page_token=None, page_size=100
    )

    assert [item.resource_id for item in page.items] == [task.resource_id for task in tasks]
    assert page.next_page_token == "provider-page-2"
    assert gateway.calls == [
        {
            "task_list_id": "list",
            "page_token": None,
            "page_size": 100,
            "show_completed": False,
            "show_hidden": False,
            "show_deleted": False,
        }
    ]


def test_tasks_browse_returns_terminal_41_items_without_snapshot_cursor() -> None:
    tasks = tuple(_task(index, None) for index in range(41))
    gateway = _PagedTaskGateway({None: ResourcePage(tasks, None)})

    page = ConnectorResourceAccess(gateway=gateway).list_tasks(
        task_list_id="list", page_token=None, page_size=100
    )

    assert len(page.items) == 41
    assert page.next_page_token is None
    assert [item.resource_id for item in page.items] == [task.resource_id for task in tasks]


@pytest.mark.parametrize("item_count", [0, 1, 20, 21, 41, 100])
def test_tasks_browse_keeps_terminal_provider_batch_sizes(item_count: int) -> None:
    tasks = tuple(_task(index, None) for index in range(item_count))
    gateway = _PagedTaskGateway({None: ResourcePage(tasks, None)})

    page = ConnectorResourceAccess(gateway=gateway).list_tasks(
        task_list_id="list", page_token=None, page_size=100
    )

    assert len(page.items) == item_count
    assert page.next_page_token is None
    assert gateway.calls[0]["page_size"] == 100


def test_tasks_browse_uses_provider_next_page_token_for_later_batch() -> None:
    first = tuple(_task(index, None) for index in range(100))
    second = tuple(_task(index, None) for index in range(100, 141))
    gateway = _PagedTaskGateway({None: ResourcePage(first, "p2"), "p2": ResourcePage(second, None)})
    service = ConnectorResourceAccess(gateway=gateway)

    first_page = service.list_tasks(task_list_id="list", page_token=None, page_size=100)
    second_page = service.list_tasks(
        task_list_id="list", page_token=first_page.next_page_token, page_size=100
    )

    assert [len(first_page.items), len(second_page.items)] == [100, 41]
    assert second_page.next_page_token is None
    assert [call["page_token"] for call in gateway.calls] == [None, "p2"]


def _snapshot(*, payload: dict[str, object]) -> ResourceSnapshot:
    return ResourceSnapshot(
        fixture_snapshot_id="thread-1",
        resource_type=ResourceType.GMAIL_THREAD,
        resource_id="thread-1",
        parent_id=None,
        related_resource_ids=(),
        version="7",
        recovery_fingerprint=None,
        payload=payload,
    )
