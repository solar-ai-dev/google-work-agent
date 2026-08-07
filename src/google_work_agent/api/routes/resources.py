"""Google Workspace resource projection routes."""

from dataclasses import asdict

from fastapi import APIRouter, Header, Query, Request

from google_work_agent.api.dependencies import (
    enforce_access,
    enforce_api_contract_version,
    get_container,
)
from google_work_agent.api.errors import ApiError
from google_work_agent.api.schemas.resources import ResourceListResponse
from google_work_agent.ports import EndpointPolicy

router = APIRouter(prefix="/api/v1/resources")


@router.get("/gmail", response_model=ResourceListResponse)
def list_gmail_resources(
    request: Request,
    query: str = Query(default=""),
    page_token: str | None = Query(default=None),
    page_size: int = Query(default=20, ge=1, le=50),
    x_api_contract_version: str | None = Header(default=None),
) -> ResourceListResponse:
    container = get_container(request)
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_api_contract_version(
        container=container,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    service = container.resource_query_service
    if service is None:
        raise ApiError(
            error_code="SERVICE_BUSY",
            user_message="Resource provider is not configured.",
            status_code=503,
            request_id=request.state.request_id,
            detail_code="RESOURCE_QUERY_UNAVAILABLE",
        )
    page = service.list_gmail_threads(query=query, page_token=page_token, page_size=page_size)
    return ResourceListResponse(
        source=page.source,
        items=[asdict(item) for item in page.items],
        next_page_token=page.next_page_token,
        api_contract_version=container.api_contract_version,
    )


@router.get("/tasks", response_model=ResourceListResponse)
def list_task_resources(
    request: Request,
    task_list_id: str | None = Query(default=None),
    page_token: str | None = Query(default=None),
    page_size: int = Query(default=20, ge=1, le=50),
    x_api_contract_version: str | None = Header(default=None),
) -> ResourceListResponse:
    container = get_container(request)
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_api_contract_version(
        container=container,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    service = container.resource_query_service
    if service is None:
        raise ApiError(
            error_code="SERVICE_BUSY",
            user_message="Resource provider is not configured.",
            status_code=503,
            request_id=request.state.request_id,
            detail_code="RESOURCE_QUERY_UNAVAILABLE",
        )
    page = service.list_tasks(
        task_list_id=task_list_id,
        page_token=page_token,
        page_size=page_size,
    )
    return ResourceListResponse(
        source=page.source,
        items=[asdict(item) for item in page.items],
        next_page_token=page.next_page_token,
        api_contract_version=container.api_contract_version,
    )


@router.get("/calendar", response_model=ResourceListResponse)
def list_calendar_resources(
    request: Request,
    calendar_id: str | None = Query(default=None),
    page_token: str | None = Query(default=None),
    page_size: int = Query(default=20, ge=1, le=50),
    x_api_contract_version: str | None = Header(default=None),
) -> ResourceListResponse:
    container = get_container(request)
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_api_contract_version(
        container=container,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    service = container.resource_query_service
    if service is None:
        raise ApiError(
            error_code="SERVICE_BUSY",
            user_message="Resource provider is not configured.",
            status_code=503,
            request_id=request.state.request_id,
            detail_code="RESOURCE_QUERY_UNAVAILABLE",
        )
    page = service.list_calendar_resources(
        calendar_id=calendar_id,
        page_token=page_token,
        page_size=page_size,
    )
    return ResourceListResponse(
        source=page.source,
        items=[asdict(item) for item in page.items],
        next_page_token=page.next_page_token,
        api_contract_version=container.api_contract_version,
    )
