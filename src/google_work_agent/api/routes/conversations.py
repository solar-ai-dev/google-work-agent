"""Conversation routes."""

from dataclasses import asdict

from fastapi import APIRouter, Header, Query, Request, Response, status

from google_work_agent.adapters.runtime import RuntimeOperation
from google_work_agent.api.dependencies import (
    enforce_access,
    enforce_api_contract_version,
    enforce_runtime_operation,
    get_container,
)
from google_work_agent.api.errors import ApiError, http_status_for_result_code
from google_work_agent.api.schemas.conversations import (
    ConversationListResponse,
    ConversationResponse,
    CreateConversationRequest,
    LatestConversationRunResponse,
)
from google_work_agent.application.start_run import CreateConversationCommand
from google_work_agent.ports import EndpointPolicy

router = APIRouter(prefix="/api/v1/conversations")


@router.post("", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
def create_conversation(
    request: Request,
    payload: CreateConversationRequest,
    response: Response,
) -> ConversationResponse:
    container = get_container(request)
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_api_contract_version(
        container=container,
        request_id=request.state.request_id,
        request_version=payload.api_contract_version,
    )
    enforce_runtime_operation(request, operation=RuntimeOperation.RUN_COMMANDS)
    result = container.create_conversation_service(
        CreateConversationCommand(**payload.model_dump())
    )
    response.status_code = http_status_for_result_code(
        result.result_code,
        default_success=201,
    )
    return ConversationResponse(**asdict(result))


@router.get("", response_model=ConversationListResponse)
def list_conversations(
    request: Request,
    account_id: str = Query(...),
    cursor: str | None = Query(default=None),
    page_size: int = Query(default=20, ge=1, le=100),
    x_api_contract_version: str | None = Header(default=None),
) -> ConversationListResponse:
    container = get_container(request)
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_api_contract_version(
        container=container,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    page = container.query_service.list_conversations(
        account_id=account_id,
        cursor=cursor,
        page_size=page_size,
    )
    return ConversationListResponse(
        items=[asdict(item) for item in page.items],
        next_cursor=page.next_cursor,
        api_contract_version=container.api_contract_version,
    )


@router.get("/{conversation_id}", response_model=ConversationListResponse)
def get_conversation(
    conversation_id: str,
    request: Request,
    x_api_contract_version: str | None = Header(default=None),
) -> ConversationListResponse:
    container = get_container(request)
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_api_contract_version(
        container=container,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    conversation = container.query_service.get_conversation(conversation_id)
    if conversation is None:
        raise ApiError(
            error_code="NOT_FOUND",
            user_message="대화를 찾을 수 없습니다.",
            status_code=404,
            request_id=request.state.request_id,
        )
    return ConversationListResponse(
        items=[asdict(conversation)],
        next_cursor=None,
        api_contract_version=container.api_contract_version,
    )


@router.get("/{conversation_id}/latest-run", response_model=LatestConversationRunResponse)
def get_latest_conversation_run(
    conversation_id: str,
    request: Request,
    x_api_contract_version: str | None = Header(default=None),
) -> LatestConversationRunResponse:
    container = get_container(request)
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_api_contract_version(
        container=container,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    run = container.query_service.get_latest_run_for_conversation(conversation_id)
    return LatestConversationRunResponse(
        run=None if run is None else asdict(run),
        api_contract_version=container.api_contract_version,
    )
