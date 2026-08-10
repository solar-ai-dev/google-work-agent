from __future__ import annotations

from datetime import UTC, datetime

from google_work_agent.application.resource_queries import ResourceQueryService
from google_work_agent.ports import (
    GmailAttachmentMetadata,
    GmailThreadDetail,
    ResourcePage,
    ResourceSnapshot,
    ResourceType,
)


class _Gateway:
    def __init__(self, snapshot: ResourceSnapshot) -> None:
        self.snapshot = snapshot

    def search_gmail_threads(
        self,
        *,
        query: str,
        page_token: str | None,
        page_size: int,
    ) -> ResourcePage:
        assert query == "project"
        assert page_token == "page-1"
        assert page_size == 10
        return ResourcePage(items=(self.snapshot,), next_page_token="page-2")

    def list_tasks(
        self,
        *,
        task_list_id: str,
        page_token: str | None,
        page_size: int,
    ) -> ResourcePage:
        return ResourcePage(items=(self.snapshot,), next_page_token=None)


class _DetailGateway:
    def get_thread_detail(self, *, thread_id: str) -> GmailThreadDetail:
        assert thread_id == "thread-1"
        return GmailThreadDetail(
            thread_id=thread_id,
            message_id="message-2",
            sender_name="Kim Daeri",
            sender_email="kim.daeri@example.com",
            recipients=("user@example.com",),
            cc=("team@example.com",),
            subject="Q2 campaign follow-up",
            received_at="Mon, 10 Aug 2026 09:15:00 +0900",
            body="Actual message body",
            attachments=(
                GmailAttachmentMetadata(
                    message_id="message-2",
                    attachment_id="attachment-1",
                    filename="report.pdf",
                    mime_type="application/pdf",
                    size_bytes=2048,
                ),
            ),
            version="8",
        )


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
    ) -> ResourcePage:
        self.calls.append(
            (
                "list_tasks",
                {
                    "task_list_id": task_list_id,
                    "page_token": page_token,
                    "page_size": page_size,
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
                    payload=self.task_payload or {
                        "title": "후속 조치",
                        "due": "2026-08-12T09:00:00+09:00",
                        "status": "needsAction",
                        "priority": "높음",
                    },
                ),
            ),
            next_page_token="tasks-next",
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
    service = ResourceQueryService(gateway=_Gateway(snapshot))

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


def test_gmail_list_projection_does_not_use_resource_id_as_title_fallback() -> None:
    service = ResourceQueryService(gateway=_Gateway(_snapshot(payload={})))

    item = service.list_gmail_threads(query="project", page_token="page-1", page_size=10).items[0]

    assert item.resource_id == "thread-1"
    assert item.title == ""
    assert item.subject is None
    assert item.metadata == {}


def test_gmail_detail_projection_is_ui_only_and_preserves_thread_identity() -> None:
    service = ResourceQueryService(
        gateway=_Gateway(_snapshot(payload={})),
        gmail_detail_gateway=_DetailGateway(),
    )

    detail = service.get_gmail_thread_detail(resource_id="thread-1")

    assert detail.resource_id == "thread-1"
    assert detail.message_id == "message-2"
    assert detail.sender_name == "Kim Daeri"
    assert detail.recipients == ("user@example.com",)
    assert detail.body == "Actual message body"
    assert detail.canonical_url.endswith("/#inbox/thread-1")
    assert detail.attachments[0].attachment_id == "attachment-1"


def test_tasks_sidebar_uses_configured_default_task_list_for_actual_tasks() -> None:
    gateway = _TaskGateway()
    service = ResourceQueryService(
        gateway=gateway,
        default_tasklist_id_provider=lambda: "configured-task-list",
    )

    page = service.list_tasks(task_list_id=None, page_token="tasks-page-1", page_size=10)

    assert gateway.calls == [
        (
            "list_tasks",
            {
                "task_list_id": "configured-task-list",
                "page_token": "tasks-page-1",
                "page_size": 10,
            },
        )
    ]
    assert page.next_page_token == "tasks-next"
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
        },
    )
    service = ResourceQueryService(gateway=_Gateway(snapshot))

    item = service.list_tasks(task_list_id="task-list-default", page_token=None, page_size=10).items[0]

    assert item.metadata == {"task_status": "completed", "scheduled_date": "2026-08-11"}


def test_tasks_sidebar_resolves_first_actual_task_list_before_listing_tasks() -> None:
    gateway = _TaskGateway()
    service = ResourceQueryService(gateway=gateway, default_tasklist_id_provider=lambda: None)

    page = service.list_tasks(task_list_id=None, page_token="tasks-page-1", page_size=10)

    assert gateway.calls == [
        ("list_task_lists", {"page_token": None, "page_size": 1}),
        (
            "list_tasks",
            {
                "task_list_id": "task-list-default",
                "page_token": "tasks-page-1",
                "page_size": 10,
            },
        ),
    ]
    assert page.items[0].resource_type == "task"


def test_calendar_sidebar_queries_upcoming_events_from_configured_default_calendar() -> None:
    gateway = _CalendarGateway()
    service = ResourceQueryService(
        gateway=gateway,
        default_calendar_id_provider=lambda: "work-calendar",
        now=lambda: datetime(2026, 8, 10, 0, 0, tzinfo=UTC),
    )

    page = service.list_calendar_resources(
        calendar_id=None,
        time_min=None,
        page_token="events-page-1",
        page_size=10,
    )

    assert gateway.arguments == {
        "calendar_id": "work-calendar",
        "page_token": "events-page-1",
        "page_size": 10,
        "time_min": "2026-08-10T00:00:00+00:00",
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
    service = ResourceQueryService(
        gateway=gateway,
        default_calendar_id_provider=lambda: None,
        now=lambda: datetime(2026, 8, 10, 0, 0, tzinfo=UTC),
    )

    service.list_calendar_resources(
        calendar_id=None,
        time_min="2026-08-10T01:00:00Z",
        page_token=None,
        page_size=10,
    )

    assert gateway.arguments is not None
    assert gateway.arguments["calendar_id"] == "primary"
    assert gateway.arguments["time_min"] == "2026-08-10T01:00:00Z"


def test_calendar_ui_projection_hides_snapshot_id_title_fallback() -> None:
    gateway = _CalendarGateway(event_title="event-1")
    service = ResourceQueryService(
        gateway=gateway,
        now=lambda: datetime(2026, 8, 10, 0, 0, tzinfo=UTC),
    )

    page = service.list_calendar_resources(
        calendar_id="primary",
        time_min="2026-08-10T01:00:00Z",
        page_token=None,
        page_size=10,
    )

    assert page.items[0].resource_id == "event-1"
    assert page.items[0].title == ""


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
