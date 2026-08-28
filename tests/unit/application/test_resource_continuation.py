from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest

from google_work_agent.application.use_cases.resource.opaque_continuation_access import (
    LocalResourceContinuationStore,
    OpaqueConnectorResourceAccess,
)
from google_work_agent.application.use_cases.resource.connector_resource_access import (
    GmailResourceDetail,
    ResourceCount,
    ResourceListPage,
)
from google_work_agent.ports import GoogleWorkspaceErrorCode, GoogleWorkspaceGatewayError


class _ResourceServiceStub:
    def __init__(self) -> None:
        self.gmail_page_tokens: list[str | None] = []
        self.task_page_tokens: list[str | None] = []

    def get_gmail_thread_detail(self, *, resource_id: str) -> GmailResourceDetail:
        raise AssertionError(f"detail path not expected in this test: {resource_id}")

    def list_gmail_threads(
        self,
        *,
        query: str,
        page_token: str | None,
        page_size: int,
        include_thread_metadata: bool = True,
    ) -> ResourceListPage:
        del query, page_size, include_thread_metadata
        self.gmail_page_tokens.append(page_token)
        return ResourceListPage(
            source="gmail",
            items=(),
            next_page_token="provider-next-gmail" if page_token is None else None,
        )

    def list_tasks(
        self,
        *,
        task_list_id: str | None,
        page_token: str | None,
        page_size: int,
        status_scope: str = "incomplete",
    ) -> ResourceListPage:
        del task_list_id, page_size, status_scope
        self.task_page_tokens.append(page_token)
        return ResourceListPage(
            source="tasks",
            items=(),
            next_page_token="provider-next-tasks" if page_token is None else None,
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
        del calendar_id, time_min, time_max, page_size
        return ResourceListPage(
            source="calendar",
            items=(),
            next_page_token="provider-next-calendar" if page_token is None else None,
        )

    def count_gmail_threads(self, *, query: str = "") -> ResourceCount:
        del query
        return ResourceCount(source="gmail", total_count=1)

    def count_tasks(self, *, task_list_id: str | None) -> ResourceCount:
        del task_list_id
        return ResourceCount(source="tasks", total_count=1)

    def count_calendar_resources(
        self,
        *,
        calendar_id: str | None,
        time_min: str | None,
        time_max: str | None,
    ) -> ResourceCount:
        del calendar_id, time_min, time_max
        return ResourceCount(source="calendar", total_count=1)


def _token_factory(values: Iterator[str]) -> Callable[[], str]:
    return lambda: next(values)


def test_provider_page_token_is_replaced_by_server_local_handle() -> None:
    raw = _ResourceServiceStub()
    store = LocalResourceContinuationStore(
        token_factory=_token_factory(iter(("local-gmail-1", "local-gmail-2")))
    )
    service = OpaqueConnectorResourceAccess(raw, continuation_store=store)

    first = service.list_gmail_threads(
        query="in:inbox",
        page_token=None,
        page_size=20,
    )

    assert raw.gmail_page_tokens == [None]
    assert first.next_page_token == "local-gmail-1"
    assert first.next_page_token != "provider-next-gmail"

    second = service.list_gmail_threads(
        query="in:inbox",
        page_token=first.next_page_token,
        page_size=20,
    )

    assert raw.gmail_page_tokens == [None, "provider-next-gmail"]
    assert second.next_page_token is None


def test_provider_token_cannot_be_replayed_as_a_local_continuation() -> None:
    raw = _ResourceServiceStub()
    service = OpaqueConnectorResourceAccess(raw)

    with pytest.raises(GoogleWorkspaceGatewayError) as caught:
        service.list_gmail_threads(
            query="in:inbox",
            page_token="provider-next-gmail",
            page_size=20,
        )

    assert caught.value.code is GoogleWorkspaceErrorCode.INVALID_ARGUMENT
    assert raw.gmail_page_tokens == []


def test_local_continuation_is_bound_to_its_exact_query_scope() -> None:
    raw = _ResourceServiceStub()
    store = LocalResourceContinuationStore(
        token_factory=_token_factory(iter(("local-scope-1", "local-scope-2")))
    )
    service = OpaqueConnectorResourceAccess(raw, continuation_store=store)

    first = service.list_gmail_threads(query="alpha", page_token=None, page_size=20)
    assert first.next_page_token == "local-scope-1"

    with pytest.raises(GoogleWorkspaceGatewayError) as caught:
        service.list_gmail_threads(
            query="beta",
            page_token=first.next_page_token,
            page_size=20,
        )

    assert caught.value.code is GoogleWorkspaceErrorCode.INVALID_ARGUMENT
    assert raw.gmail_page_tokens == [None]


def test_local_continuation_cannot_cross_resource_sources() -> None:
    raw = _ResourceServiceStub()
    store = LocalResourceContinuationStore(
        token_factory=_token_factory(iter(("local-source-1", "local-source-2")))
    )
    service = OpaqueConnectorResourceAccess(raw, continuation_store=store)

    gmail = service.list_gmail_threads(query="", page_token=None, page_size=20)

    with pytest.raises(GoogleWorkspaceGatewayError) as caught:
        service.list_tasks(
            task_list_id="tasks-1",
            page_token=gmail.next_page_token,
            page_size=100,
        )

    assert caught.value.code is GoogleWorkspaceErrorCode.INVALID_ARGUMENT
    assert raw.task_page_tokens == []


def test_count_paths_do_not_allocate_or_resolve_continuations() -> None:
    raw = _ResourceServiceStub()
    service = OpaqueConnectorResourceAccess(raw)

    assert service.count_gmail_threads(query="").total_count == 1
    assert service.count_tasks(task_list_id=None).total_count == 1
    assert (
        service.count_calendar_resources(calendar_id=None, time_min=None, time_max=None).total_count
        == 1
    )
