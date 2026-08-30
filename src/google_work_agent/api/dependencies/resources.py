"""Resource route dependency contract and provider."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from google_work_agent.api.dependencies.request_context import get_api_container
from google_work_agent.application.use_cases.resource.get_calendar_resource_detail import (
    GetCalendarResourceDetailHandler,
)
from google_work_agent.application.use_cases.resource.get_resource_count import (
    GetResourceCountHandler,
)
from google_work_agent.application.use_cases.resource.get_resource_detail import (
    GetResourceDetailHandler,
)
from google_work_agent.application.use_cases.resource.get_task_resource_detail import (
    GetTaskResourceDetailHandler,
)
from google_work_agent.application.use_cases.resource.issue_selection_handle import (
    IssueSelectionHandle,
)
from google_work_agent.application.use_cases.resource.list_calendars import ListCalendarsHandler
from google_work_agent.application.use_cases.resource.list_resources import ListResourcesHandler
from google_work_agent.application.use_cases.resource.list_task_lists import ListTaskListsHandler
from google_work_agent.application.use_cases.resource.resolve_selection_handle import (
    ResolveSelectionHandle,
)


@dataclass(frozen=True, slots=True)
class ResourceRouteDependencies:
    api_contract_version: str
    issue_selection_handle: IssueSelectionHandle
    resolve_selection_handle: ResolveSelectionHandle
    service_instance_id: str
    resource_connector_id: str
    current_account_id: Callable[[], str | None]
    list_task_lists_handler: ListTaskListsHandler | None
    list_calendars_handler: ListCalendarsHandler | None
    list_resources_handler: ListResourcesHandler | None
    get_resource_count_handler: GetResourceCountHandler | None
    get_resource_detail_handler: GetResourceDetailHandler | None
    get_task_resource_detail_handler: GetTaskResourceDetailHandler | None
    get_calendar_resource_detail_handler: GetCalendarResourceDetailHandler | None


def get_resource_route_dependencies(request: Request) -> ResourceRouteDependencies:
    container = get_api_container(request)
    issue_selection_handle = container.issue_selection_handle
    resolve_selection_handle = container.resolve_selection_handle
    if issue_selection_handle is None or resolve_selection_handle is None:
        raise RuntimeError("selection-handle operations are not configured")
    return ResourceRouteDependencies(
        api_contract_version=container.api_contract_version,
        issue_selection_handle=issue_selection_handle,
        resolve_selection_handle=resolve_selection_handle,
        service_instance_id=container.service_instance_id,
        resource_connector_id=container.resource_connector_id,
        current_account_id=container.current_account_id_provider,
        list_task_lists_handler=container.list_task_lists_handler,
        list_calendars_handler=container.list_calendars_handler,
        list_resources_handler=container.list_resources_handler,
        get_resource_count_handler=container.get_resource_count_handler,
        get_resource_detail_handler=container.get_resource_detail_handler,
        get_task_resource_detail_handler=container.get_task_resource_detail_handler,
        get_calendar_resource_detail_handler=container.get_calendar_resource_detail_handler,
    )


ResourceRouteDependency = Annotated[
    ResourceRouteDependencies,
    Depends(get_resource_route_dependencies),
]
