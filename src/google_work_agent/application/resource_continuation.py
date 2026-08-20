"""Server-local opaque continuation boundary for UI resource pagination.

Provider page tokens are transport/session internals. The local HTTP API may
return an opaque continuation handle, but it must never expose the provider
value itself.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from secrets import token_urlsafe
from threading import RLock
from typing import Any

from google_work_agent.application.resource_queries import (
    GmailResourceDetail,
    ResourceCount,
    ResourceListPage,
)
from google_work_agent.ports import GoogleWorkspaceErrorCode, GoogleWorkspaceGatewayError

ContinuationScope = tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _StoredContinuation:
    scope: ContinuationScope
    provider_page_token: str


class LocalResourceContinuationStore:
    """In-memory map from local opaque handles to provider page tokens.

    The store is intentionally process-local and non-persistent. Handles are
    bound to the exact local query scope so one source/query cannot replay a
    continuation issued for another source/query.
    """

    def __init__(self, *, token_factory: Callable[[], str] | None = None) -> None:
        self._token_factory = token_factory or (lambda: token_urlsafe(24))
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
            )
        return local_handle

    def resolve(self, *, scope: ContinuationScope, local_handle: str) -> str:
        with self._lock:
            stored = self._values.get(local_handle)
        if stored is None or stored.scope != scope:
            raise _invalid_continuation()
        return stored.provider_page_token


class OpaqueResourceQueryService:
    """UI resource-query facade that hides provider pagination tokens."""

    def __init__(
        self,
        service: Any,
        *,
        continuation_store: LocalResourceContinuationStore | None = None,
    ) -> None:
        self._service = service
        self._continuations = continuation_store or LocalResourceContinuationStore()

    def get_gmail_thread_detail(self, *, resource_id: str) -> GmailResourceDetail:
        return self._service.get_gmail_thread_detail(resource_id=resource_id)

    def list_gmail_threads(
        self,
        *,
        query: str,
        page_token: str | None,
        page_size: int,
        include_thread_metadata: bool = True,
    ) -> ResourceListPage:
        scope = (
            "gmail",
            query.strip(),
            str(page_size),
            "metadata" if include_thread_metadata else "no-metadata",
        )
        provider_token = self._resolve(scope=scope, local_handle=page_token)
        page = self._service.list_gmail_threads(
            query=query,
            page_token=provider_token,
            page_size=page_size,
            include_thread_metadata=include_thread_metadata,
        )
        return self._localize(page=page, scope=scope)

    def list_tasks(
        self,
        *,
        task_list_id: str | None,
        page_token: str | None,
        page_size: int,
        status_scope: str = "incomplete",
    ) -> ResourceListPage:
        scope = (
            "tasks",
            task_list_id or "",
            str(page_size),
            status_scope,
        )
        provider_token = self._resolve(scope=scope, local_handle=page_token)
        page = self._service.list_tasks(
            task_list_id=task_list_id,
            page_token=provider_token,
            page_size=page_size,
            status_scope=status_scope,
        )
        return self._localize(page=page, scope=scope)

    def list_calendar_resources(
        self,
        *,
        calendar_id: str | None,
        time_min: str | None,
        time_max: str | None,
        page_token: str | None,
        page_size: int,
    ) -> ResourceListPage:
        scope = (
            "calendar",
            calendar_id or "",
            time_min or "",
            time_max or "",
            str(page_size),
        )
        provider_token = self._resolve(scope=scope, local_handle=page_token)
        page = self._service.list_calendar_resources(
            calendar_id=calendar_id,
            time_min=time_min,
            time_max=time_max,
            page_token=provider_token,
            page_size=page_size,
        )
        return self._localize(page=page, scope=scope)

    def count_gmail_threads(self, *, query: str = "") -> ResourceCount:
        return self._service.count_gmail_threads(query=query)

    def count_tasks(self, *, task_list_id: str | None) -> ResourceCount:
        return self._service.count_tasks(task_list_id=task_list_id)

    def count_calendar_resources(
        self,
        *,
        calendar_id: str | None,
        time_min: str | None,
        time_max: str | None,
    ) -> ResourceCount:
        return self._service.count_calendar_resources(
            calendar_id=calendar_id,
            time_min=time_min,
            time_max=time_max,
        )

    def _resolve(
        self,
        *,
        scope: ContinuationScope,
        local_handle: str | None,
    ) -> str | None:
        if local_handle is None:
            return None
        return self._continuations.resolve(scope=scope, local_handle=local_handle)

    def _localize(
        self,
        *,
        page: ResourceListPage,
        scope: ContinuationScope,
    ) -> ResourceListPage:
        provider_next = page.next_page_token
        if provider_next is None:
            return ResourceListPage(source=page.source, items=page.items, next_page_token=None)
        local_next = self._continuations.issue(
            scope=scope,
            provider_page_token=provider_next,
        )
        return ResourceListPage(
            source=page.source,
            items=page.items,
            next_page_token=local_next,
        )


def _invalid_continuation() -> GoogleWorkspaceGatewayError:
    return GoogleWorkspaceGatewayError(
        code=GoogleWorkspaceErrorCode.INVALID_ARGUMENT,
        message="local resource continuation is invalid for this query",
        delivered=False,
        mutated=False,
    )
