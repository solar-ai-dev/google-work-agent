"""Resource projection routes over canonical Application use cases."""

from dataclasses import asdict
from typing import cast

from fastapi import APIRouter, Header, Path, Query, Request

from google_work_agent.api.dependencies.access_control import enforce_access
from google_work_agent.api.dependencies.contract_version import (
    enforce_supported_api_contract_version,
)
from google_work_agent.api.dependencies.resources import ResourceRouteDependency
from google_work_agent.api.errors.api_request_error import ApiRequestError
from google_work_agent.api.schemas.resources.count_resources import ResourceCountResponse
from google_work_agent.api.schemas.resources.get_gmail_resource import GmailResourceDetailResponse
from google_work_agent.api.schemas.resources.list_resources import ResourceListResponse
from google_work_agent.api.security.cookies import LOCAL_SESSION_COOKIE_NAME
from google_work_agent.api.security.sessions import calculate_session_digest
from google_work_agent.application.use_cases.resource.get_calendar_resource_detail import (
    GetCalendarResourceDetailHandler,
    GetCalendarResourceDetailQuery,
)
from google_work_agent.application.use_cases.resource.get_resource_count import (
    GetResourceCountHandler,
    GetResourceCountQuery,
)
from google_work_agent.application.use_cases.resource.get_resource_detail import (
    GetResourceDetailHandler,
    GetResourceDetailQuery,
)
from google_work_agent.application.use_cases.resource.get_task_resource_detail import (
    GetTaskResourceDetailHandler,
    GetTaskResourceDetailQuery,
)
from google_work_agent.application.use_cases.resource.issue_selection_handle import (
    IssueSelectionHandleCommand,
)
from google_work_agent.application.use_cases.resource.list_calendars import (
    ListCalendarsHandler,
    ListCalendarsQuery,
)
from google_work_agent.application.use_cases.resource.list_resources import (
    ListResourcesHandler,
    ListResourcesQuery,
    ResourceListItem,
)
from google_work_agent.application.use_cases.resource.list_task_lists import (
    ListTaskListsHandler,
    ListTaskListsQuery,
)
from google_work_agent.application.use_cases.resource.opaque_continuation_access import (
    ResourceAccess,
)
from google_work_agent.ports.connector.connector_failure import (
    ConnectorFailureCode,
    ConnectorOperationFailure,
)
from google_work_agent.ports.system.api_access_port import EndpointPolicy

router = APIRouter(prefix="/api/v1/resources")


@router.get("/task-lists")
def list_task_lists(
    request: Request,
    dependencies: ResourceRouteDependency,
    page_token: str | None = Query(default=None),
    page_size: int = Query(default=50, ge=1, le=100),
    x_api_contract_version: str | None = Header(default=None),
) -> dict[str, object]:
    _enforce_resource_access(request, dependencies, x_api_contract_version)
    handler = dependencies.list_task_lists_handler
    if not isinstance(handler, ListTaskListsHandler):
        _raise_resource_handler_unavailable(request)
    result = cast(ListTaskListsHandler, handler)(ListTaskListsQuery(page_token, page_size))
    return cast(dict[str, object], asdict(result))


@router.get("/calendars")
def list_calendars(
    request: Request,
    dependencies: ResourceRouteDependency,
    page_token: str | None = Query(default=None),
    page_size: int = Query(default=50, ge=1, le=100),
    x_api_contract_version: str | None = Header(default=None),
) -> dict[str, object]:
    _enforce_resource_access(request, dependencies, x_api_contract_version)
    handler = dependencies.list_calendars_handler
    if not isinstance(handler, ListCalendarsHandler):
        _raise_resource_handler_unavailable(request)
    result = cast(ListCalendarsHandler, handler)(ListCalendarsQuery(page_token, page_size))
    return cast(dict[str, object], asdict(result))


def _resource_service(dependencies: ResourceRouteDependency, *, request_id: str) -> ResourceAccess:
    service = dependencies.resource_query_service()
    if service is None:
        raise ApiRequestError(
            error_code="SERVICE_BUSY",
            user_message="Resource provider is not configured.",
            status_code=503,
            request_id=request_id,
            detail_code="RESOURCE_QUERY_UNAVAILABLE",
        )
    return service


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
    try:
        result = ListResourcesHandler(
            _resource_service(dependencies, request_id=request.state.request_id)
        )(
            ListResourcesQuery(
                source="gmail",
                query=query,
                page_token=page_token,
                page_size=page_size,
                include_thread_metadata=include_thread_metadata,
            )
        )
    except ConnectorOperationFailure as error:
        _raise_connector_failure(error, request_id=request.state.request_id)
    page = result.page
    return ResourceListResponse(
        source=page.source,
        items=_items_with_selection_handles(request, dependencies, page.items),
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
    del refresh
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(
        supported_version=dependencies.api_contract_version,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    try:
        result = GetResourceCountHandler(
            _resource_service(dependencies, request_id=request.state.request_id)
        )(
            GetResourceCountQuery(
                source=source,
                query=query,
                task_list_id=task_list_id,
                calendar_id=calendar_id,
                time_min=time_min,
                time_max=time_max,
            )
        )
    except ConnectorOperationFailure as error:
        _raise_connector_failure(error, request_id=request.state.request_id)
    count = result.count
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
    try:
        result = GetResourceDetailHandler(
            _resource_service(dependencies, request_id=request.state.request_id)
        )(GetResourceDetailQuery(source="gmail", resource_id=resource_id))
    except ConnectorOperationFailure as error:
        _raise_connector_failure(error, request_id=request.state.request_id)
    return GmailResourceDetailResponse(
        **asdict(result.resource),
        api_contract_version=dependencies.api_contract_version,
    )


@router.get("/tasks/{resource_id}")
def get_task_resource_detail(
    request: Request,
    dependencies: ResourceRouteDependency,
    resource_id: str = Path(min_length=1, max_length=2048),
    selection_handle: str = Query(min_length=1, max_length=4096),
    x_api_contract_version: str | None = Header(default=None),
) -> dict[str, object]:
    _enforce_resource_access(request, dependencies, x_api_contract_version)
    session_digest, account_id = _selection_identity(request, dependencies)
    handler = dependencies.get_task_resource_detail_handler
    if not isinstance(handler, GetTaskResourceDetailHandler):
        _raise_resource_handler_unavailable(request)
    try:
        result = cast(GetTaskResourceDetailHandler, handler)(
            GetTaskResourceDetailQuery(
                resource_id=resource_id,
                selection_handle=selection_handle,
                session_digest=session_digest,
                account_id=account_id,
            )
        )
    except ValueError as error:
        _raise_invalid_selection(error, request_id=request.state.request_id)
    return {"schema_version": 1, "detail": result.detail}


@router.get("/calendar/{resource_id}")
def get_calendar_resource_detail(
    request: Request,
    dependencies: ResourceRouteDependency,
    resource_id: str = Path(min_length=1, max_length=2048),
    selection_handle: str = Query(min_length=1, max_length=4096),
    x_api_contract_version: str | None = Header(default=None),
) -> dict[str, object]:
    _enforce_resource_access(request, dependencies, x_api_contract_version)
    session_digest, account_id = _selection_identity(request, dependencies)
    handler = dependencies.get_calendar_resource_detail_handler
    if not isinstance(handler, GetCalendarResourceDetailHandler):
        _raise_resource_handler_unavailable(request)
    try:
        result = cast(GetCalendarResourceDetailHandler, handler)(
            GetCalendarResourceDetailQuery(
                resource_id=resource_id,
                selection_handle=selection_handle,
                session_digest=session_digest,
                account_id=account_id,
            )
        )
    except ValueError as error:
        _raise_invalid_selection(error, request_id=request.state.request_id)
    return {"schema_version": 1, "detail": result.detail}


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
    del refresh
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(
        supported_version=dependencies.api_contract_version,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    try:
        result = ListResourcesHandler(
            _resource_service(dependencies, request_id=request.state.request_id)
        )(
            ListResourcesQuery(
                source="tasks",
                task_list_id=task_list_id,
                page_token=page_token,
                page_size=page_size,
                status_scope=status_scope,
            )
        )
    except ConnectorOperationFailure as error:
        _raise_connector_failure(error, request_id=request.state.request_id)
    page = result.page
    return ResourceListResponse(
        source=page.source,
        items=_items_with_selection_handles(request, dependencies, page.items),
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
    try:
        result = ListResourcesHandler(
            _resource_service(dependencies, request_id=request.state.request_id)
        )(
            ListResourcesQuery(
                source="calendar",
                calendar_id=calendar_id,
                time_min=time_min,
                time_max=time_max,
                page_token=page_token,
                page_size=page_size,
            )
        )
    except ConnectorOperationFailure as error:
        _raise_connector_failure(error, request_id=request.state.request_id)
    page = result.page
    return ResourceListResponse(
        source=page.source,
        items=_items_with_selection_handles(request, dependencies, page.items),
        next_page_token=page.next_page_token,
        api_contract_version=dependencies.api_contract_version,
    )


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
    raise ApiRequestError(
        error_code=error_code,
        user_message="Resource request could not be completed.",
        status_code=status_code,
        request_id=request_id,
        retryable=error.retryable,
        detail_code=error.detail_code,
    ) from error


def _enforce_resource_access(
    request: Request,
    dependencies: ResourceRouteDependency,
    request_version: str | None,
) -> None:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(
        supported_version=dependencies.api_contract_version,
        request_id=request.state.request_id,
        request_version=request_version,
    )


def _raise_resource_handler_unavailable(request: Request) -> None:
    raise ApiRequestError(
        error_code="SERVICE_BUSY",
        user_message="Resource provider is not configured.",
        status_code=503,
        request_id=request.state.request_id,
        detail_code="RESOURCE_QUERY_UNAVAILABLE",
    )


def _selection_identity(request: Request, dependencies: ResourceRouteDependency) -> tuple[str, str]:
    session_token = request.cookies.get(LOCAL_SESSION_COOKIE_NAME)
    account_id = dependencies.current_account_id()
    if session_token is None or account_id is None:
        raise ApiRequestError(
            error_code="LOCAL_SESSION_INVALID",
            user_message="Resource selection requires an active account and local session.",
            status_code=401,
            request_id=request.state.request_id,
            detail_code="RESOURCE_SELECTION_BINDING_UNAVAILABLE",
        )
    return calculate_session_digest(session_token), account_id


def _raise_invalid_selection(error: ValueError, *, request_id: str) -> None:
    raise ApiRequestError(
        error_code="INVALID_ARGUMENT",
        user_message="Resource selection is invalid.",
        status_code=422,
        request_id=request_id,
        detail_code="RESOURCE_SELECTION_INVALID",
    ) from error


def _items_with_selection_handles(
    request: Request,
    dependencies: ResourceRouteDependency,
    items: tuple[ResourceListItem, ...],
) -> list[dict[str, object]]:
    session_token = request.cookies.get(LOCAL_SESSION_COOKIE_NAME)
    account_id = dependencies.current_account_id()
    if session_token is None or account_id is None:
        raise ApiRequestError(
            error_code="LOCAL_SESSION_INVALID",
            user_message="Resource selection requires an active account and local session.",
            status_code=401,
            request_id=request.state.request_id,
            detail_code="RESOURCE_SELECTION_BINDING_UNAVAILABLE",
        )
    session_digest = calculate_session_digest(session_token)
    projected: list[dict[str, object]] = []
    for item in items:
        values = asdict(item)
        values["selection_handle"] = dependencies.issue_selection_handle(
            IssueSelectionHandleCommand(
                session_digest=session_digest,
                account_id=account_id,
                connector_id=dependencies.resource_connector_id,
                resource_type=str(values["resource_type"]),
                resource_id=str(values["resource_id"]),
                parent_resource_id=(
                    None if values.get("parent_id") is None else str(values["parent_id"])
                ),
                version_token=None if values.get("version") is None else str(values["version"]),
            )
        )
        projected.append(values)
    return projected
