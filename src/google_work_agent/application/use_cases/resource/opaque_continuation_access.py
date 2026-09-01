"""Server-local opaque continuation boundary for UI resource pagination.

Provider page tokens are transport/session internals. The local HTTP API may
return an opaque continuation handle, but it must never expose the provider
value itself.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from secrets import token_urlsafe
from threading import RLock
from time import time
from typing import Protocol

from google_work_agent.ports.connector.contracts.google_workspace import (
    GmailThreadDetail,
    GoogleWorkspaceErrorCode,
    GoogleWorkspaceGatewayError,
    ResourcePage,
)

ContinuationScope = tuple[str, ...]


class ResourceAccess(Protocol):
    """Narrow connector/config/time collaborators used by resource handlers."""

    def get_gmail_thread_detail_raw(self, *, resource_id: str) -> GmailThreadDetail: ...

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

    def count_gmail_page(
        self,
        *,
        query: str,
        page_token: str | None,
        page_size: int,
        include_thread_metadata: bool,
    ) -> ResourcePage: ...

    def count_task_lists_page(
        self,
        *,
        page_token: str | None,
        page_size: int,
    ) -> ResourcePage: ...

    def count_tasks_page(
        self,
        *,
        task_list_id: str,
        page_token: str | None,
        page_size: int,
        show_completed: bool,
    ) -> ResourcePage: ...

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
    ) -> ResourcePage: ...

    def default_task_list_id(self) -> str | None: ...

    def default_calendar_id(self) -> str | None: ...

    def timezone_name(self) -> str: ...

    def current_time(self) -> datetime: ...


@dataclass(frozen=True, slots=True)
class _StoredContinuation:
    scope: ContinuationScope
    provider_page_token: str
    expires_at_ms: int


class LocalResourceContinuationStore:
    """In-memory map from local opaque handles to provider page tokens."""

    def __init__(
        self,
        *,
        token_factory: Callable[[], str] | None = None,
        now_ms: Callable[[], int] | None = None,
        ttl_ms: int = 5 * 60 * 1000,
    ) -> None:
        if ttl_ms < 1:
            raise ValueError("resource continuation TTL must be positive")
        self._token_factory = token_factory or (lambda: token_urlsafe(24))
        self._now_ms = now_ms or (lambda: int(time() * 1000))
        self._ttl_ms = ttl_ms
        self._values: dict[str, _StoredContinuation] = {}
        self._lock = RLock()

    def issue(self, *, scope: ContinuationScope, provider_page_token: str) -> str:
        if not provider_page_token:
            raise ValueError("provider page token must be non-empty")
        local_handle = self._token_factory()
        if not local_handle:
            raise RuntimeError("local continuation factory returned an empty handle")
        with self._lock:
            if local_handle in self._values:
                raise RuntimeError("local continuation handle collision")
            self._values[local_handle] = _StoredContinuation(
                scope=scope,
                provider_page_token=provider_page_token,
                expires_at_ms=self._now_ms() + self._ttl_ms,
            )
        return local_handle

    def resolve(self, *, scope: ContinuationScope, local_handle: str) -> str:
        with self._lock:
            stored = self._values.get(local_handle)
            if stored is not None and stored.expires_at_ms <= self._now_ms():
                self._values.pop(local_handle, None)
                stored = None
        if stored is None or stored.scope != scope:
            raise _invalid_continuation()
        return stored.provider_page_token


class OpaqueConnectorResourceAccess:
    """Issue and validate local opaque continuations around resource reads."""

    def __init__(
        self,
        service: ResourceAccess,
        *,
        continuation_store: LocalResourceContinuationStore | None = None,
    ) -> None:
        self._service = service
        self._continuations = continuation_store or LocalResourceContinuationStore()

    def get_gmail_thread_detail_raw(self, *, resource_id: str) -> GmailThreadDetail:
        return self._service.get_gmail_thread_detail_raw(resource_id=resource_id)

    def list_gmail_page(
        self,
        *,
        query: str,
        page_token: str | None,
        page_size: int,
        include_thread_metadata: bool,
        continuation_scope: tuple[str, ...],
    ) -> ResourcePage:
        provider_token = self._resolve(
            scope=continuation_scope,
            local_handle=page_token,
        )
        page = self._service.list_gmail_page(
            query=query,
            page_token=provider_token,
            page_size=page_size,
            include_thread_metadata=include_thread_metadata,
            continuation_scope=continuation_scope,
        )
        return self._localize_resource_page(page=page, scope=continuation_scope)

    def list_task_lists_page(
        self,
        *,
        page_token: str | None,
        page_size: int,
    ) -> ResourcePage:
        return self._service.list_task_lists_page(page_token=page_token, page_size=page_size)

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
        provider_token = self._resolve(
            scope=continuation_scope,
            local_handle=page_token,
        )
        page = self._service.list_tasks_page(
            task_list_id=task_list_id,
            page_token=provider_token,
            page_size=page_size,
            show_completed=show_completed,
            show_hidden=show_hidden,
            show_deleted=show_deleted,
            continuation_scope=continuation_scope,
        )
        return self._localize_resource_page(page=page, scope=continuation_scope)

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
        return self._service.list_tasks_materialization_page(
            task_list_id=task_list_id,
            page_token=page_token,
            page_size=page_size,
            show_completed=show_completed,
            show_hidden=show_hidden,
            show_deleted=show_deleted,
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
        provider_token = self._resolve(
            scope=continuation_scope,
            local_handle=page_token,
        )
        page = self._service.list_calendar_events_page(
            calendar_id=calendar_id,
            page_token=provider_token,
            page_size=page_size,
            time_min=time_min,
            time_max=time_max,
            single_events=single_events,
            order_by=order_by,
            continuation_scope=continuation_scope,
        )
        return self._localize_resource_page(page=page, scope=continuation_scope)

    def count_gmail_page(
        self,
        *,
        query: str,
        page_token: str | None,
        page_size: int,
        include_thread_metadata: bool,
    ) -> ResourcePage:
        return self._service.count_gmail_page(
            query=query,
            page_token=page_token,
            page_size=page_size,
            include_thread_metadata=include_thread_metadata,
        )

    def count_task_lists_page(
        self,
        *,
        page_token: str | None,
        page_size: int,
    ) -> ResourcePage:
        return self._service.count_task_lists_page(page_token=page_token, page_size=page_size)

    def count_tasks_page(
        self,
        *,
        task_list_id: str,
        page_token: str | None,
        page_size: int,
        show_completed: bool,
    ) -> ResourcePage:
        return self._service.count_tasks_page(
            task_list_id=task_list_id,
            page_token=page_token,
            page_size=page_size,
            show_completed=show_completed,
        )

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
        return self._service.count_calendar_events_page(
            calendar_id=calendar_id,
            page_token=page_token,
            page_size=page_size,
            time_min=time_min,
            time_max=time_max,
            single_events=single_events,
            order_by=order_by,
        )

    def default_task_list_id(self) -> str | None:
        return self._service.default_task_list_id()

    def default_calendar_id(self) -> str | None:
        return self._service.default_calendar_id()

    def timezone_name(self) -> str:
        return self._service.timezone_name()

    def current_time(self) -> datetime:
        return self._service.current_time()

    def _resolve(
        self,
        *,
        scope: ContinuationScope,
        local_handle: str | None,
    ) -> str | None:
        if local_handle is None:
            return None
        return self._continuations.resolve(scope=scope, local_handle=local_handle)

    def _localize_resource_page(
        self,
        *,
        page: ResourcePage,
        scope: ContinuationScope,
    ) -> ResourcePage:
        provider_next = page.next_page_token
        if provider_next is None:
            return ResourcePage(items=page.items, next_page_token=None)
        local_next = self._continuations.issue(
            scope=scope,
            provider_page_token=provider_next,
        )
        return ResourcePage(items=page.items, next_page_token=local_next)


def _invalid_continuation() -> GoogleWorkspaceGatewayError:
    return GoogleWorkspaceGatewayError(
        code=GoogleWorkspaceErrorCode.INVALID_ARGUMENT,
        message="local resource continuation is invalid for this query",
        delivered=False,
        mutated=False,
    )
