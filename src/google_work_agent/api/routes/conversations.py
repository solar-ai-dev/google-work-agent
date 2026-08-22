"""Conversation routes."""

from dataclasses import asdict

from fastapi import APIRouter, Header, Query, Request, Response, status

from google_work_agent.api.dependencies.access_control import enforce_access
from google_work_agent.api.dependencies.contract_version import (
    enforce_supported_api_contract_version,
)
from google_work_agent.api.dependencies.conversations import ConversationRouteDependency
from google_work_agent.api.dependencies.request_hash import calculate_server_request_hash
from google_work_agent.api.dependencies.runtime_operation import enforce_runtime_operation
from google_work_agent.api.errors.api_request_error import ApiRequestError
from google_work_agent.api.errors.result_code_http_mapping import http_status_for_result_code
from google_work_agent.api.schemas.conversations.create_conversation import (
    ConversationResponse,
    CreateConversationRequest,
)
from google_work_agent.api.schemas.conversations.get_conversation_history import (
    ConversationHistoryResponse,
)
from google_work_agent.api.schemas.conversations.get_latest_run import LatestConversationRunResponse
from google_work_agent.api.schemas.conversations.list_conversations import ConversationListResponse
from google_work_agent.application.use_cases.conversation.create_conversation import (
    CreateConversationCommand,
    CreateConversationHandler,
)
from google_work_agent.application.use_cases.conversation.get_conversation import (
    GetConversationHandler,
    GetConversationQuery,
)
from google_work_agent.application.use_cases.conversation.get_conversation_history import (
    GetConversationHistoryHandler,
    GetConversationHistoryQuery,
)
from google_work_agent.application.use_cases.conversation.get_latest_run import (
    GetLatestRunHandler,
    GetLatestRunQuery,
)
from google_work_agent.application.use_cases.conversation.list_conversations import (
    ListConversationsHandler,
    ListConversationsQuery,
)
from google_work_agent.ports import EndpointPolicy

router = APIRouter(prefix="/api/v1/conversations")


@router.post("", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
def create_conversation(
    request: Request,
    payload: CreateConversationRequest,
    response: Response,
    dependencies: ConversationRouteDependency,
) -> ConversationResponse:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(
        supported_version=dependencies.api_contract_version,
        request_id=request.state.request_id,
        request_version=payload.api_contract_version,
    )
    enforce_runtime_operation(request, operation="RUN_COMMANDS")
    command_payload = payload.model_dump()
    command_payload["request_hash"] = calculate_server_request_hash(
        operation="CreateConversationRequestV1", payload=command_payload
    )
    result = CreateConversationHandler.from_legacy_service_supplier(
        dependencies.create_conversation_service
    )(CreateConversationCommand(**command_payload))
    response.status_code = http_status_for_result_code(result.result_code, default_success=201)
    return ConversationResponse(**asdict(result))


@router.get("", response_model=ConversationListResponse)
def list_conversations(
    request: Request,
    dependencies: ConversationRouteDependency,
    account_id: str = Query(...),
    cursor: str | None = Query(default=None),
    page_size: int = Query(default=20, ge=1, le=100),
    x_api_contract_version: str | None = Header(default=None),
) -> ConversationListResponse:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(
        supported_version=dependencies.api_contract_version,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    result = ListConversationsHandler.from_legacy_query_supplier(dependencies.query_service)(
        ListConversationsQuery(account_id=account_id, cursor=cursor, page_size=page_size)
    )
    return ConversationListResponse(
        items=[asdict(item) for item in result.items],
        next_cursor=result.next_cursor,
        api_contract_version=dependencies.api_contract_version,
    )


@router.get("/{conversation_id}", response_model=ConversationListResponse)
def get_conversation(
    conversation_id: str,
    request: Request,
    dependencies: ConversationRouteDependency,
    x_api_contract_version: str | None = Header(default=None),
) -> ConversationListResponse:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(
        supported_version=dependencies.api_contract_version,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    conversation = GetConversationHandler.from_legacy_query_supplier(dependencies.query_service)(
        GetConversationQuery(conversation_id=conversation_id)
    )
    if conversation is None:
        raise ApiRequestError(
            error_code="NOT_FOUND",
            user_message="대화를 찾을 수 없습니다.",
            status_code=404,
            request_id=request.state.request_id,
        )
    return ConversationListResponse(
        items=[asdict(conversation)],
        next_cursor=None,
        api_contract_version=dependencies.api_contract_version,
    )


@router.get("/{conversation_id}/history", response_model=ConversationHistoryResponse)
def get_conversation_history(
    conversation_id: str,
    request: Request,
    dependencies: ConversationRouteDependency,
    x_api_contract_version: str | None = Header(default=None),
) -> ConversationHistoryResponse:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(
        supported_version=dependencies.api_contract_version,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    history = GetConversationHistoryHandler.from_legacy_query_supplier(dependencies.query_service)(
        GetConversationHistoryQuery(conversation_id=conversation_id)
    )
    if history is None:
        raise ApiRequestError(
            error_code="NOT_FOUND",
            user_message="대화를 찾을 수 없습니다.",
            status_code=404,
            request_id=request.state.request_id,
        )
    return ConversationHistoryResponse(
        conversation=asdict(history.conversation),
        messages=[asdict(item) for item in history.messages],
        runs=[asdict(item) for item in history.runs],
        truncated=history.truncated,
        api_contract_version=dependencies.api_contract_version,
    )


@router.get("/{conversation_id}/latest-run", response_model=LatestConversationRunResponse)
def get_latest_conversation_run(
    conversation_id: str,
    request: Request,
    dependencies: ConversationRouteDependency,
    x_api_contract_version: str | None = Header(default=None),
) -> LatestConversationRunResponse:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(
        supported_version=dependencies.api_contract_version,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    run = GetLatestRunHandler.from_legacy_query_supplier(dependencies.query_service)(
        GetLatestRunQuery(conversation_id=conversation_id)
    )
    return LatestConversationRunResponse(
        run=None if run is None else asdict(run),
        api_contract_version=dependencies.api_contract_version,
    )
