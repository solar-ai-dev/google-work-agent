"""List external resources through the canonical resource_ref query boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from google_work_agent.application.ports.connector_failure import (
    ConnectorFailureCode,
    ConnectorOperationFailure,
    normalize_google_workspace_failure,
)
from google_work_agent.ports import GoogleWorkspaceGatewayError


@dataclass(frozen=True, slots=True)
class ListResourcesQuery:
    source: str
    query: str = ""
    page_token: str | None = None
    page_size: int = 20
    include_thread_metadata: bool = True
    task_list_id: str | None = None
    status_scope: str = "incomplete"
    calendar_id: str | None = None
    time_min: str | None = None
    time_max: str | None = None


@dataclass(frozen=True, slots=True)
class ListResourcesResult:
    page: Any


@dataclass(frozen=True, slots=True)
class ListResourcesHandler:
    resource_query_service: Any

    def __call__(self, query: ListResourcesQuery) -> ListResourcesResult:
        try:
            if query.source == "gmail":
                page = self.resource_query_service.list_gmail_threads(
                    query=query.query,
                    page_token=query.page_token,
                    page_size=query.page_size,
                    include_thread_metadata=query.include_thread_metadata,
                )
            elif query.source == "tasks":
                page = self.resource_query_service.list_tasks(
                    task_list_id=query.task_list_id,
                    page_token=query.page_token,
                    page_size=query.page_size,
                    status_scope=query.status_scope,
                )
            elif query.source == "calendar":
                page = self.resource_query_service.list_calendar_resources(
                    calendar_id=query.calendar_id,
                    time_min=query.time_min,
                    time_max=query.time_max,
                    page_token=query.page_token,
                    page_size=query.page_size,
                )
            else:
                raise ConnectorOperationFailure(
                    code=ConnectorFailureCode.NOT_FOUND,
                    detail_code="RESOURCE_SOURCE_NOT_FOUND",
                )
        except GoogleWorkspaceGatewayError as error:
            raise normalize_google_workspace_failure(error) from error
        except ValueError as error:
            raise ConnectorOperationFailure(
                code=ConnectorFailureCode.INVALID_ARGUMENT,
                detail_code="RESOURCE_QUERY_INVALID",
            ) from error
        return ListResourcesResult(page=page)
