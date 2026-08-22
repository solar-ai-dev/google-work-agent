"""Count external resources through the canonical resource_ref query boundary."""

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
class CountResourcesQuery:
    source: str
    query: str = ""
    task_list_id: str | None = None
    calendar_id: str | None = None
    time_min: str | None = None
    time_max: str | None = None


@dataclass(frozen=True, slots=True)
class CountResourcesResult:
    count: Any


@dataclass(frozen=True, slots=True)
class CountResourcesHandler:
    resource_query_service: Any

    def __call__(self, query: CountResourcesQuery) -> CountResourcesResult:
        try:
            if query.source == "gmail":
                count = self.resource_query_service.count_gmail_threads(query=query.query)
            elif query.source == "tasks":
                count = self.resource_query_service.count_tasks(task_list_id=query.task_list_id)
            elif query.source == "calendar":
                count = self.resource_query_service.count_calendar_resources(
                    calendar_id=query.calendar_id,
                    time_min=query.time_min,
                    time_max=query.time_max,
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
        return CountResourcesResult(count=count)
