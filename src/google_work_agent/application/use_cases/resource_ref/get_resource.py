"""Get one external resource via the resource_ref query boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from google_work_agent.application.ports.connector_failure import ConnectorFailureCode, ConnectorOperationFailure, normalize_google_workspace_failure
from google_work_agent.ports import GoogleWorkspaceGatewayError


@dataclass(frozen=True, slots=True)
class GetResourceQuery:
    source: str
    resource_id: str


@dataclass(frozen=True, slots=True)
class GetResourceResult:
    resource: Any


@dataclass(frozen=True, slots=True)
class GetResourceHandler:
    resource_query_service: Any

    def __call__(self, query: GetResourceQuery) -> GetResourceResult:
        if query.source != "gmail":
            raise ConnectorOperationFailure(code=ConnectorFailureCode.NOT_FOUND, detail_code="RESOURCE_SOURCE_NOT_FOUND")
        try:
            resource = self.resource_query_service.get_gmail_thread_detail(resource_id=query.resource_id)
        except GoogleWorkspaceGatewayError as error:
            raise normalize_google_workspace_failure(error) from error
        except RuntimeError as error:
            raise ConnectorOperationFailure(code=ConnectorFailureCode.CONNECTION_UNAVAILABLE, detail_code="RESOURCE_DETAIL_UNAVAILABLE", retryable=True) from error
        return GetResourceResult(resource=resource)
