from __future__ import annotations

from google_work_agent.application.resource_queries import ResourceQueryService
from google_work_agent.ports import ResourcePage, ResourceSnapshot, ResourceType


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
