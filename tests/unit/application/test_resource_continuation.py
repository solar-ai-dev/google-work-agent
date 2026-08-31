from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import TypedDict, Unpack

import pytest

from google_work_agent.application.use_cases.resource.get_resource_count import (
    GetResourceCountHandler,
    GetResourceCountQuery,
    ResourceCount,
)
from google_work_agent.application.use_cases.resource.get_resource_detail import (
    GmailResourceDetail,
)
from google_work_agent.application.use_cases.resource.list_resources import (
    ListResourcesHandler,
    ListResourcesQuery,
    ResourceListPage,
)
from google_work_agent.application.use_cases.resource.opaque_continuation_access import (
    LocalResourceContinuationStore,
)
from google_work_agent.application.use_cases.resource.opaque_continuation_access import (
    OpaqueConnectorResourceAccess as _OpaqueConnectorResourceAccess,
)
from google_work_agent.ports.connector.connector_failure import (
    ConnectorFailureCode,
    ConnectorOperationFailure,
)
from google_work_agent.ports.connector.contracts.google_workspace import (
    GmailThreadDetail,
    GoogleWorkspaceGatewayError,
    ResourcePage,
)


class _ListResourceKwargs(TypedDict, total=False):
    query: str
    page_token: str | None
    page_size: int
    include_thread_metadata: bool
    task_list_id: str | None
    status_scope: str
    calendar_id: str | None
    time_min: str | None
    time_max: str | None


class OpaqueConnectorResourceAccess(_OpaqueConnectorResourceAccess):
    """Test-only convenience surface that calls the exact canonical handlers."""

    def list_gmail_threads(self, **kwargs: Unpack[_ListResourceKwargs]) -> ResourceListPage:
        return ListResourcesHandler(self)(
            ListResourcesQuery(
                source="gmail", session_digest="a" * 64, account_id="account-1", **kwargs
            )
        ).page

    def list_tasks(self, **kwargs: Unpack[_ListResourceKwargs]) -> ResourceListPage:
        return ListResourcesHandler(self)(
            ListResourcesQuery(
                source="tasks", session_digest="a" * 64, account_id="account-1", **kwargs
            )
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


class _ResourceServiceStub:
    def __init__(self) -> None:
        self.gmail_page_tokens: list[str | None] = []
        self.task_page_tokens: list[str | None] = []

    def get_gmail_thread_detail(self, *, resource_id: str) -> GmailResourceDetail:
        raise AssertionError(f"detail path not expected in this test: {resource_id}")

    def get_gmail_thread_detail_raw(self, *, resource_id: str) -> GmailThreadDetail:
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
        page = self.list_gmail_threads(
            query=query,
            page_token=page_token,
            page_size=page_size,
            include_thread_metadata=include_thread_metadata,
        )
        return ResourcePage(items=(), next_page_token=page.next_page_token)

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
        del show_completed, show_hidden, show_deleted, continuation_scope
        page = self.list_tasks(
            task_list_id=task_list_id,
            page_token=page_token,
            page_size=page_size,
        )
        return ResourcePage(items=(), next_page_token=page.next_page_token)

    def list_tasks_materialization_page(self, **kwargs: object) -> ResourcePage:
        return self.list_tasks_page(continuation_scope=(), **kwargs)  # type: ignore[arg-type]

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

    def list_calendar_events_page(self, **kwargs: object) -> ResourcePage:
        page = self.list_calendar_resources(
            calendar_id=kwargs.get("calendar_id"),  # type: ignore[arg-type]
            time_min=kwargs.get("time_min"),  # type: ignore[arg-type]
            time_max=kwargs.get("time_max"),  # type: ignore[arg-type]
            page_token=kwargs.get("page_token"),  # type: ignore[arg-type]
            page_size=kwargs.get("page_size", 100),  # type: ignore[arg-type]
        )
        return ResourcePage(items=(), next_page_token=page.next_page_token)

    def list_task_lists_page(self, *, page_token: str | None, page_size: int) -> ResourcePage:
        del page_token, page_size
        return ResourcePage(items=(), next_page_token=None)

    def count_gmail_threads(self, *, query: str = "") -> ResourceCount:
        del query
        return ResourceCount(source="gmail", total_count=1)

    def count_gmail_page(self, **kwargs: object) -> ResourcePage:
        del kwargs
        return ResourcePage(items=(), next_page_token=None)

    def count_tasks(self, *, task_list_id: str | None) -> ResourceCount:
        del task_list_id
        return ResourceCount(source="tasks", total_count=1)

    def count_task_lists_page(self, *, page_token: str | None, page_size: int) -> ResourcePage:
        del page_token, page_size
        return ResourcePage(items=(), next_page_token=None)

    def count_tasks_page(self, **kwargs: object) -> ResourcePage:
        del kwargs
        return ResourcePage(items=(), next_page_token=None)

    def count_calendar_resources(
        self,
        *,
        calendar_id: str | None,
        time_min: str | None,
        time_max: str | None,
    ) -> ResourceCount:
        del calendar_id, time_min, time_max
        return ResourceCount(source="calendar", total_count=1)

    def count_calendar_events_page(self, **kwargs: object) -> ResourcePage:
        del kwargs
        return ResourcePage(items=(), next_page_token=None)

    def default_task_list_id(self) -> str | None:
        return "tasks"

    def default_calendar_id(self) -> str | None:
        return "primary"

    def timezone_name(self) -> str:
        return "UTC"

    def current_time(self) -> datetime:
        return datetime(2026, 1, 1, tzinfo=UTC)


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

    with pytest.raises(ConnectorOperationFailure) as caught:
        service.list_gmail_threads(
            query="in:inbox",
            page_token="provider-next-gmail",
            page_size=20,
        )

    assert caught.value.code is ConnectorFailureCode.INVALID_ARGUMENT
    assert raw.gmail_page_tokens == []


def test_local_continuation_is_bound_to_its_exact_query_scope() -> None:
    raw = _ResourceServiceStub()
    store = LocalResourceContinuationStore(
        token_factory=_token_factory(iter(("local-scope-1", "local-scope-2")))
    )
    service = OpaqueConnectorResourceAccess(raw, continuation_store=store)

    first = service.list_gmail_threads(query="alpha", page_token=None, page_size=20)
    assert first.next_page_token == "local-scope-1"

    with pytest.raises(ConnectorOperationFailure) as caught:
        service.list_gmail_threads(
            query="beta",
            page_token=first.next_page_token,
            page_size=20,
        )

    assert caught.value.code is ConnectorFailureCode.INVALID_ARGUMENT
    assert raw.gmail_page_tokens == [None]


def test_local_continuation_cannot_cross_resource_sources() -> None:
    raw = _ResourceServiceStub()
    store = LocalResourceContinuationStore(
        token_factory=_token_factory(iter(("local-source-1", "local-source-2")))
    )
    service = OpaqueConnectorResourceAccess(raw, continuation_store=store)

    gmail = service.list_gmail_threads(query="", page_token=None, page_size=20)

    with pytest.raises(ConnectorOperationFailure) as caught:
        service.list_tasks(
            task_list_id="tasks-1",
            page_token=gmail.next_page_token,
            page_size=100,
        )

    assert caught.value.code is ConnectorFailureCode.INVALID_ARGUMENT
    assert raw.task_page_tokens == []


def test_count_paths_do_not_allocate_or_resolve_continuations() -> None:
    raw = _ResourceServiceStub()
    service = OpaqueConnectorResourceAccess(raw)

    assert service.count_gmail_threads(query="").total_count == 0
    assert service.count_tasks(task_list_id=None).total_count == 0
    assert (
        service.count_calendar_resources(calendar_id=None, time_min=None, time_max=None).total_count
        == 0
    )


def test_local_continuation_is_session_account_bound_and_expires() -> None:
    now_ms = 100
    store = LocalResourceContinuationStore(
        token_factory=lambda: "local-bound",
        now_ms=lambda: now_ms,
        ttl_ms=10,
    )
    scope = ("a" * 64, "account-1", "gmail", "", "20", "metadata")
    handle = store.issue(scope=scope, provider_page_token="provider-secret")

    with pytest.raises(GoogleWorkspaceGatewayError):
        store.resolve(
            scope=("b" * 64, "account-1", "gmail", "", "20", "metadata"),
            local_handle=handle,
        )
    with pytest.raises(GoogleWorkspaceGatewayError):
        store.resolve(
            scope=("a" * 64, "account-2", "gmail", "", "20", "metadata"),
            local_handle=handle,
        )

    now_ms = 110
    with pytest.raises(GoogleWorkspaceGatewayError):
        store.resolve(scope=scope, local_handle=handle)
