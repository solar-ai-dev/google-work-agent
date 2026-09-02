from datetime import UTC, datetime

import pytest

from google_work_agent.application.use_cases.resource.list_resources import (
    GMAIL_PRIMARY_QUERY,
    ListResourcesHandler,
    ListResourcesQuery,
)
from google_work_agent.ports.connector.connector_failure import ConnectorOperationFailure
from google_work_agent.ports.connector.contracts.google_workspace import (
    ResourcePage,
    ResourceSnapshot,
    ResourceType,
)


class _Access:
    def __init__(self) -> None:
        self.gmail_query: str | None = None

    def list_gmail_page(self, **kwargs: object) -> ResourcePage:
        self.gmail_query = str(kwargs["query"])
        return ResourcePage(
            items=(
                ResourceSnapshot(
                    fixture_snapshot_id="thread-1",
                    resource_type=ResourceType.GMAIL_THREAD,
                    resource_id="thread-1",
                    parent_id=None,
                    related_resource_ids=("message-1",),
                    version="7",
                    recovery_fingerprint=None,
                    payload={"subject": "Status", "snippet": "Ready"},
                ),
            ),
            next_page_token="next-1",
        )

    def list_task_lists_page(self, *, page_token: str | None, page_size: int) -> ResourcePage:
        del page_token, page_size
        raise AssertionError("task-list access is outside this test")

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
        del (
            task_list_id,
            page_token,
            page_size,
            show_completed,
            show_hidden,
            show_deleted,
            continuation_scope,
        )
        raise AssertionError("task access is outside this test")

    def list_tasks_materialization_page(
        self,
        *,
        task_list_id: str,
        page_token: str | None,
        page_size: int,
        show_completed: bool,
        show_hidden: bool,
        show_deleted: bool,
    ) -> ResourcePage:
        del task_list_id, page_token, page_size, show_completed, show_hidden, show_deleted
        raise AssertionError("task materialization is outside this test")

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
        del (
            calendar_id,
            page_token,
            page_size,
            time_min,
            time_max,
            single_events,
            order_by,
            continuation_scope,
        )
        raise AssertionError("calendar access is outside this test")

    def default_task_list_id(self) -> str | None:
        return None

    def default_calendar_id(self) -> str | None:
        return None

    def timezone_name(self) -> str:
        return "UTC"

    def current_time(self) -> datetime:
        return datetime(2026, 8, 28, tzinfo=UTC)


def test_list_resources_projects__bounded_gmail_page__with_default_query() -> None:
    access = _Access()
    result = ListResourcesHandler(access)(
        ListResourcesQuery(
            source="gmail", session_digest="a" * 64, account_id="account-1", page_size=20
        )
    )

    assert access.gmail_query == GMAIL_PRIMARY_QUERY
    assert result.page.source == "gmail"
    assert result.page.next_page_token == "next-1"
    assert result.page.items[0].resource_id == "thread-1"
    assert result.page.items[0].subject == "Status"


def test_list_resources__rejects_unknown_source__without_provider_call() -> None:
    access = _Access()

    with pytest.raises(ConnectorOperationFailure) as error:
        ListResourcesHandler(access)(
            ListResourcesQuery(source="drive", session_digest="a" * 64, account_id="account-1")
        )

    assert error.value.detail_code == "RESOURCE_SOURCE_NOT_FOUND"
    assert access.gmail_query is None
