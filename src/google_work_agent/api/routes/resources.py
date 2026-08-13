"""Google Workspace resource projection routes."""

from dataclasses import asdict

from fastapi import APIRouter, Header, Path, Query, Request

from google_work_agent.api.dependencies import (
    ResourceRouteDependency,
    enforce_access,
    enforce_supported_api_contract_version,
)
from google_work_agent.api.errors import ApiError
from google_work_agent.api.schemas.resources import (
    GmailResourceDetailResponse,
    ResourceCountResponse,
    ResourceListResponse,
)
from google_work_agent.ports import (
    EndpointPolicy,
    GoogleWorkspaceErrorCode,
    GoogleWorkspaceGatewayError,
)

router = APIRouter(prefix="/api/v1/resources")


@router.get("/gmail", response_model=ResourceListResponse)
def list_gmail_resources(
    request: Request,
    dependencies: ResourceRouteDependency,
    query: str = Query(default=""),
    page_token: str | None = Query(default=None),
    page_size: int = Query(default=20, ge=1, le=100),
    include_thread_metadata: bool = Query(default=True),
    x_api_contract_version: str | None = Header(default=None),
) -> ResourceListResponse:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(
        supported_version=dependencies.api_contract_version,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    service = dependencies.resource_query_service()
    if service is None:
        raise ApiError(
            error_code="SERVICE_BUSY",
            user_message="Resource provider is not configured.",
            status_code=503,
            request_id=request.state.request_id,
            detail_code="RESOURCE_QUERY_UNAVAILABLE",
        )
    try:
        page = service.list_gmail_threads(
            query=query,
            page_token=page_token,
            page_size=page_size,
            include_thread_metadata=include_thread_metadata,
        )
    except GoogleWorkspaceGatewayError as error:
        _raise_resource_error(error, request_id=request.state.request_id)
    return ResourceListResponse(
        source=page.source,
        items=[asdict(item) for item in page.items],
        next_page_token=page.next_page_token,
        api_contract_version=dependencies.api_contract_version,
    )


@router.get("/{source}/count", response_model=ResourceCountResponse)
def get_resource_count(
    request: Request,
    dependencies: ResourceRouteDependency,
    source: str = Path(min_length=1, max_length=32),
    query: str = Query(default=""),
    task_list_id: str | None = Query(default=None),
    calendar_id: str | None = Query(default=None),
    time_min: str | None = Query(default=None, min_length=1, max_length=64),
    time_max: str | None = Query(default=None, min_length=1, max_length=64),
    refresh: bool = Query(default=False),
    x_api_contract_version: str | None = Header(default=None),
) -> ResourceCountResponse:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(
        supported_version=dependencies.api_contract_version,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    service = dependencies.resource_query_service()
    if service is None:
        raise ApiError(
            error_code="SERVICE_BUSY",
            user_message="Resource provider is not configured.",
            status_code=503,
            request_id=request.state.request_id,
            detail_code="RESOURCE_QUERY_UNAVAILABLE",
        )
    try:
        if source == "gmail":
            count = service.count_gmail_threads(query=query)
        elif source == "tasks":
            count = service.count_tasks(task_list_id=task_list_id)
        elif source == "calendar":
            count = service.count_calendar_resources(
                calendar_id=calendar_id,
                time_min=time_min,
                time_max=time_max,
            )
        else:
            raise ApiError(
                error_code="NOT_FOUND",
                user_message="Resource source was not found.",
                status_code=404,
                request_id=request.state.request_id,
            )
    except ValueError as error:
        raise ApiError(
            error_code="INVALID_ARGUMENT",
            user_message="Resource query parameters are invalid.",
            status_code=422,
            request_id=request.state.request_id,
        ) from error
    except GoogleWorkspaceGatewayError as error:
        _raise_resource_error(error, request_id=request.state.request_id)
    return ResourceCountResponse(
        source=count.source,
        total_count=count.total_count,
        api_contract_version=dependencies.api_contract_version,
    )


@router.get("/gmail/{resource_id}", response_model=GmailResourceDetailResponse)
def get_gmail_resource_detail(
    request: Request,
    dependencies: ResourceRouteDependency,
    resource_id: str = Path(min_length=1, max_length=2048),
    x_api_contract_version: str | None = Header(default=None),
) -> GmailResourceDetailResponse:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(
        supported_version=dependencies.api_contract_version,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    service = dependencies.resource_query_service()
    if service is None:
        raise ApiError(
            error_code="SERVICE_BUSY",
            user_message="Resource provider is not configured.",
            status_code=503,
            request_id=request.state.request_id,
            detail_code="RESOURCE_QUERY_UNAVAILABLE",
        )
    try:
        detail = service.get_gmail_thread_detail(resource_id=resource_id)
    except RuntimeError as error:
        raise ApiError(
            error_code="SERVICE_BUSY",
            user_message="Gmail detail provider is not configured.",
            status_code=503,
            request_id=request.state.request_id,
            detail_code="GMAIL_DETAIL_QUERY_UNAVAILABLE",
        ) from error
    except GoogleWorkspaceGatewayError as error:
        _raise_resource_error(error, request_id=request.state.request_id)
    return GmailResourceDetailResponse(
        **asdict(detail),
        api_contract_version=dependencies.api_contract_version,
    )


@router.get("/tasks", response_model=ResourceListResponse)
def list_task_resources(
    request: Request,
    dependencies: ResourceRouteDependency,
    task_list_id: str | None = Query(default=None),
    page_token: str | None = Query(default=None),
    page_size: int = Query(default=100, ge=1, le=100),
    status_scope: str = Query(default="incomplete", pattern="^(incomplete|completed)$"),
    refresh: bool = Query(default=False),
    x_api_contract_version: str | None = Header(default=None),
) -> ResourceListResponse:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(
        supported_version=dependencies.api_contract_version,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    service = dependencies.resource_query_service()
    if service is None:
        raise ApiError(
            error_code="SERVICE_BUSY",
            user_message="Resource provider is not configured.",
            status_code=503,
            request_id=request.state.request_id,
            detail_code="RESOURCE_QUERY_UNAVAILABLE",
        )
    try:
        page = service.list_tasks(
            task_list_id=task_list_id,
            page_token=page_token,
            page_size=page_size,
            status_scope=status_scope,
        )
    except ValueError as error:
        raise ApiError(
            error_code="INVALID_ARGUMENT",
            user_message="Resource query parameters are invalid.",
            status_code=422,
            request_id=request.state.request_id,
        ) from error
    except GoogleWorkspaceGatewayError as error:
        _raise_resource_error(error, request_id=request.state.request_id)
    return ResourceListResponse(
        source=page.source,
        items=[asdict(item) for item in page.items],
        next_page_token=page.next_page_token,
        api_contract_version=dependencies.api_contract_version,
    )


@router.get("/calendar", response_model=ResourceListResponse)
def list_calendar_resources(
    request: Request,
    dependencies: ResourceRouteDependency,
    calendar_id: str | None = Query(default=None),
    time_min: str | None = Query(default=None, min_length=1, max_length=64),
    time_max: str | None = Query(default=None, min_length=1, max_length=64),
    page_token: str | None = Query(default=None),
    page_size: int = Query(default=100, ge=1, le=100),
    x_api_contract_version: str | None = Header(default=None),
) -> ResourceListResponse:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(
        supported_version=dependencies.api_contract_version,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    service = dependencies.resource_query_service()
    if service is None:
        raise ApiError(
            error_code="SERVICE_BUSY",
            user_message="Resource provider is not configured.",
            status_code=503,
            request_id=request.state.request_id,
            detail_code="RESOURCE_QUERY_UNAVAILABLE",
        )
    try:
        page = service.list_calendar_resources(
            calendar_id=calendar_id,
            time_min=time_min,
            time_max=time_max,
            page_token=page_token,
            page_size=page_size,
        )
    except ValueError as error:
        raise ApiError(
            error_code="INVALID_ARGUMENT",
            user_message="Resource query parameters are invalid.",
            status_code=422,
            request_id=request.state.request_id,
        ) from error
    except GoogleWorkspaceGatewayError as error:
        _raise_resource_error(error, request_id=request.state.request_id)
    return ResourceListResponse(
        source=page.source,
        items=[asdict(item) for item in page.items],
        next_page_token=page.next_page_token,
        api_contract_version=dependencies.api_contract_version,
    )


def _raise_resource_error(error: GoogleWorkspaceGatewayError, *, request_id: str) -> None:
    mapping = {
        GoogleWorkspaceErrorCode.INVALID_ARGUMENT: ("INVALID_ARGUMENT", 422, False),
        GoogleWorkspaceErrorCode.AUTH_EXPIRED: ("AUTH_REQUIRED", 401, False),
        GoogleWorkspaceErrorCode.PERMISSION_DENIED: ("PERMISSION_DENIED", 403, False),
        GoogleWorkspaceErrorCode.NOT_FOUND: ("NOT_FOUND", 404, False),
        GoogleWorkspaceErrorCode.RATE_LIMITED: ("UPSTREAM_UNAVAILABLE", 429, True),
        GoogleWorkspaceErrorCode.UPSTREAM_5XX: ("UPSTREAM_UNAVAILABLE", 502, True),
        GoogleWorkspaceErrorCode.TIMEOUT: ("UPSTREAM_UNAVAILABLE", 504, True),
        GoogleWorkspaceErrorCode.CONNECTION_CLOSED: ("SERVICE_BUSY", 503, True),
        GoogleWorkspaceErrorCode.RESPONSE_MALFORMED: ("UPSTREAM_UNAVAILABLE", 502, False),
    }
    error_code, status_code, retryable = mapping.get(
        error.code,
        ("UPSTREAM_UNAVAILABLE", 502, False),
    )
    raise ApiError(
        error_code=error_code,
        user_message="Google resource request could not be completed.",
        status_code=status_code,
        request_id=request_id,
        retryable=retryable,
        detail_code=f"GOOGLE_{error.code.value}",
    ) from error
