"""Resource projection routes over canonical Application use cases."""

from dataclasses import asdict

from fastapi import APIRouter, Header, Path, Query, Request

from google_work_agent.api.dependencies import ResourceRouteDependency, enforce_access, enforce_supported_api_contract_version
from google_work_agent.api.errors import ApiError
from google_work_agent.api.schemas.resources import GmailResourceDetailResponse, ResourceCountResponse, ResourceListResponse
from google_work_agent.application.ports.connector_failure import ConnectorFailureCode, ConnectorOperationFailure
from google_work_agent.application.use_cases.resource_ref.count_resources import CountResourcesHandler, CountResourcesQuery
from google_work_agent.application.use_cases.resource_ref.get_resource import GetResourceHandler, GetResourceQuery
from google_work_agent.application.use_cases.resource_ref.list_resources import ListResourcesHandler, ListResourcesQuery
from google_work_agent.ports import EndpointPolicy

router = APIRouter(prefix="/api/v1/resources")


def _resource_service(dependencies: ResourceRouteDependency, *, request_id: str):
    service = dependencies.resource_query_service()
    if service is None:
        raise ApiError(error_code="SERVICE_BUSY", user_message="Resource provider is not configured.", status_code=503, request_id=request_id, detail_code="RESOURCE_QUERY_UNAVAILABLE")
    return service


@router.get("/gmail", response_model=ResourceListResponse)
def list_gmail_resources(request: Request, dependencies: ResourceRouteDependency, query: str = Query(default=""), page_token: str | None = Query(default=None), page_size: int = Query(default=20, ge=1, le=100), include_thread_metadata: bool = Query(default=True), x_api_contract_version: str | None = Header(default=None)) -> ResourceListResponse:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(supported_version=dependencies.api_contract_version, request_id=request.state.request_id, request_version=x_api_contract_version)
    try:
        result = ListResourcesHandler(_resource_service(dependencies, request_id=request.state.request_id))(ListResourcesQuery(source="gmail", query=query, page_token=page_token, page_size=page_size, include_thread_metadata=include_thread_metadata))
    except ConnectorOperationFailure as error:
        _raise_connector_failure(error, request_id=request.state.request_id)
    page = result.page
    return ResourceListResponse(source=page.source, items=[asdict(item) for item in page.items], next_page_token=page.next_page_token, api_contract_version=dependencies.api_contract_version)


@router.get("/{source}/count", response_model=ResourceCountResponse)
def get_resource_count(request: Request, dependencies: ResourceRouteDependency, source: str = Path(min_length=1, max_length=32), query: str = Query(default=""), task_list_id: str | None = Query(default=None), calendar_id: str | None = Query(default=None), time_min: str | None = Query(default=None, min_length=1, max_length=64), time_max: str | None = Query(default=None, min_length=1, max_length=64), refresh: bool = Query(default=False), x_api_contract_version: str | None = Header(default=None)) -> ResourceCountResponse:
    del refresh
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(supported_version=dependencies.api_contract_version, request_id=request.state.request_id, request_version=x_api_contract_version)
    try:
        result = CountResourcesHandler(_resource_service(dependencies, request_id=request.state.request_id))(CountResourcesQuery(source=source, query=query, task_list_id=task_list_id, calendar_id=calendar_id, time_min=time_min, time_max=time_max))
    except ConnectorOperationFailure as error:
        _raise_connector_failure(error, request_id=request.state.request_id)
    count = result.count
    return ResourceCountResponse(source=count.source, total_count=count.total_count, api_contract_version=dependencies.api_contract_version)


@router.get("/gmail/{resource_id}", response_model=GmailResourceDetailResponse)
def get_gmail_resource_detail(request: Request, dependencies: ResourceRouteDependency, resource_id: str = Path(min_length=1, max_length=2048), x_api_contract_version: str | None = Header(default=None)) -> GmailResourceDetailResponse:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(supported_version=dependencies.api_contract_version, request_id=request.state.request_id, request_version=x_api_contract_version)
    try:
        result = GetResourceHandler(_resource_service(dependencies, request_id=request.state.request_id))(GetResourceQuery(source="gmail", resource_id=resource_id))
    except ConnectorOperationFailure as error:
        _raise_connector_failure(error, request_id=request.state.request_id)
    return GmailResourceDetailResponse(**asdict(result.resource), api_contract_version=dependencies.api_contract_version)


@router.get("/tasks", response_model=ResourceListResponse)
def list_task_resources(request: Request, dependencies: ResourceRouteDependency, task_list_id: str | None = Query(default=None), page_token: str | None = Query(default=None), page_size: int = Query(default=100, ge=1, le=100), status_scope: str = Query(default="incomplete", pattern="^(incomplete|completed)$"), refresh: bool = Query(default=False), x_api_contract_version: str | None = Header(default=None)) -> ResourceListResponse:
    del refresh
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(supported_version=dependencies.api_contract_version, request_id=request.state.request_id, request_version=x_api_contract_version)
    try:
        result = ListResourcesHandler(_resource_service(dependencies, request_id=request.state.request_id))(ListResourcesQuery(source="tasks", task_list_id=task_list_id, page_token=page_token, page_size=page_size, status_scope=status_scope))
    except ConnectorOperationFailure as error:
        _raise_connector_failure(error, request_id=request.state.request_id)
    page = result.page
    return ResourceListResponse(source=page.source, items=[asdict(item) for item in page.items], next_page_token=page.next_page_token, api_contract_version=dependencies.api_contract_version)


@router.get("/calendar", response_model=ResourceListResponse)
def list_calendar_resources(request: Request, dependencies: ResourceRouteDependency, calendar_id: str | None = Query(default=None), time_min: str | None = Query(default=None, min_length=1, max_length=64), time_max: str | None = Query(default=None, min_length=1, max_length=64), page_token: str | None = Query(default=None), page_size: int = Query(default=100, ge=1, le=100), x_api_contract_version: str | None = Header(default=None)) -> ResourceListResponse:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(supported_version=dependencies.api_contract_version, request_id=request.state.request_id, request_version=x_api_contract_version)
    try:
        result = ListResourcesHandler(_resource_service(dependencies, request_id=request.state.request_id))(ListResourcesQuery(source="calendar", calendar_id=calendar_id, time_min=time_min, time_max=time_max, page_token=page_token, page_size=page_size))
    except ConnectorOperationFailure as error:
        _raise_connector_failure(error, request_id=request.state.request_id)
    page = result.page
    return ResourceListResponse(source=page.source, items=[asdict(item) for item in page.items], next_page_token=page.next_page_token, api_contract_version=dependencies.api_contract_version)


def _raise_connector_failure(error: ConnectorOperationFailure, *, request_id: str) -> None:
    mapping = {
        ConnectorFailureCode.INVALID_ARGUMENT: ("INVALID_ARGUMENT", 422),
        ConnectorFailureCode.AUTH_REQUIRED: ("AUTH_REQUIRED", 401),
        ConnectorFailureCode.PERMISSION_DENIED: ("PERMISSION_DENIED", 403),
        ConnectorFailureCode.NOT_FOUND: ("NOT_FOUND", 404),
        ConnectorFailureCode.RATE_LIMITED: ("UPSTREAM_UNAVAILABLE", 429),
        ConnectorFailureCode.UPSTREAM_UNAVAILABLE: ("UPSTREAM_UNAVAILABLE", 502),
        ConnectorFailureCode.TIMEOUT: ("UPSTREAM_UNAVAILABLE", 504),
        ConnectorFailureCode.CONNECTION_UNAVAILABLE: ("SERVICE_BUSY", 503),
        ConnectorFailureCode.MALFORMED_RESPONSE: ("UPSTREAM_UNAVAILABLE", 502),
        ConnectorFailureCode.CONFIGURATION_ERROR: ("CONFIGURATION_ERROR", 503),
        ConnectorFailureCode.ATTACHMENT_INVALID: ("INVALID_ATTACHMENT", 422),
    }
    error_code, status_code = mapping[error.code]
    raise ApiError(error_code=error_code, user_message="Resource request could not be completed.", status_code=status_code, request_id=request_id, retryable=error.retryable, detail_code=error.detail_code) from error
