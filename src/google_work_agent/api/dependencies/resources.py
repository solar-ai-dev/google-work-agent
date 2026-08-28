"""Resource route dependency contract and provider."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from google_work_agent.api.dependencies.request_context import get_api_container
from google_work_agent.application.use_cases.resource.connector_resource_access import (
    ConnectorResourceAccess,
)
from google_work_agent.application.use_cases.resource.issue_selection_handle import (
    IssueSelectionHandle,
)
from google_work_agent.application.use_cases.resource.resolve_selection_handle import (
    ResolveSelectionHandle,
)


@dataclass(frozen=True, slots=True)
class ResourceRouteDependencies:
    api_contract_version: str
    resource_query_service: Callable[[], ConnectorResourceAccess | None]
    issue_selection_handle: IssueSelectionHandle
    resolve_selection_handle: ResolveSelectionHandle
    service_instance_id: str
    resource_connector_id: str
    current_account_id: Callable[[], str | None]
    list_task_lists_handler: object | None
    list_calendars_handler: object | None
    get_task_resource_detail_handler: object | None
    get_calendar_resource_detail_handler: object | None


def get_resource_route_dependencies(request: Request) -> ResourceRouteDependencies:
    container = get_api_container(request)
    issue_selection_handle = container.issue_selection_handle
    resolve_selection_handle = container.resolve_selection_handle
    if issue_selection_handle is None or resolve_selection_handle is None:
        raise RuntimeError("selection-handle operations are not configured")
    return ResourceRouteDependencies(
        api_contract_version=container.api_contract_version,
        resource_query_service=lambda: container.resource_query_service,
        issue_selection_handle=issue_selection_handle,
        resolve_selection_handle=resolve_selection_handle,
        service_instance_id=container.service_instance_id,
        resource_connector_id=container.resource_connector_id,
        current_account_id=lambda: _current_account_id(container.query_service),
        list_task_lists_handler=container.list_task_lists_handler,
        list_calendars_handler=container.list_calendars_handler,
        get_task_resource_detail_handler=container.get_task_resource_detail_handler,
        get_calendar_resource_detail_handler=container.get_calendar_resource_detail_handler,
    )


def _current_account_id(query_service: object) -> str | None:
    getter = getattr(query_service, "get_current_google_account", None)
    if getter is None:
        return None
    account = getter()
    return None if account is None else str(account.account_id)


ResourceRouteDependency = Annotated[
    ResourceRouteDependencies,
    Depends(get_resource_route_dependencies),
]
