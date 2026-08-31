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
    CreateConversationRequestV1,
)
from google_work_agent.api.schemas.conversations.get_conversation_history import (
    ConversationHistoryResponseV1,
    ConversationHistoryRunV1,
    ConversationMessageV1,
)
from google_work_agent.api.schemas.conversations.list_conversations import (
    ConversationItemV1,
    ConversationListResponseV1,
)
from google_work_agent.application.use_cases.conversation.create_conversation import (
    CreateConversationCommand,
)
from google_work_agent.application.use_cases.conversation.get_conversation_history import (
    GetConversationHistoryQuery,
)
from google_work_agent.application.use_cases.conversation.list_conversations import (
    ListConversationsQuery,
)
from google_work_agent.ports.system.api_access_port import EndpointPolicy

router = APIRouter(prefix="/api/v1/conversations")


@router.post("", response_model=ConversationItemV1, status_code=status.HTTP_201_CREATED)
def create_conversation(
    request: Request,
    payload: CreateConversationRequestV1,
    response: Response,
    dependencies: ConversationRouteDependency,
) -> ConversationItemV1:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_runtime_operation(request, operation="RUN_COMMANDS")
    account_id = dependencies.current_account_id()
    if account_id is None:
        raise ApiRequestError(
            error_code="AUTH_REQUIRED",
            user_message="Google account connection is required.",
            status_code=401,
            request_id=request.state.request_id,
        )
    request_payload = payload.model_dump()
    result = dependencies.create_conversation_handler(
        CreateConversationCommand(
            command_id=payload.command_id,
            request_hash=calculate_server_request_hash(
                operation="CreateConversationRequestV1", payload=request_payload
            ),
            conversation_id=dependencies.new_id(),
            account_id=account_id,
            title=payload.title or "새 대화",
            api_contract_version=dependencies.api_contract_version,
        )
    )
    response.status_code = http_status_for_result_code(result.result_code, default_success=201)
    return ConversationItemV1(
        conversation_id=result.conversation_id,
        title=result.title,
        latest_message_at_ms=None,
        open_run_id=None,
    )


@router.get("", response_model=ConversationListResponseV1)
def list_conversations(
    request: Request,
    dependencies: ConversationRouteDependency,
    cursor: str | None = Query(default=None),
    page_size: int = Query(default=50, ge=1, le=50),
    search: str | None = Query(default=None, max_length=256),
    x_api_contract_version: str | None = Header(default=None),
) -> ConversationListResponseV1:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(
        supported_version=dependencies.api_contract_version,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    account_id = dependencies.current_account_id()
    if account_id is None:
        raise ApiRequestError(
            error_code="AUTH_REQUIRED",
            user_message="Google 계정 연결이 필요합니다.",
            status_code=401,
            request_id=request.state.request_id,
        )
    result = dependencies.list_conversations_handler(
        ListConversationsQuery(
            account_id=account_id,
            cursor=cursor,
            page_size=page_size,
            search=search,
        )
    )
    return ConversationListResponseV1(
        items=[ConversationItemV1(**asdict(item)) for item in result.items],
        next_cursor=result.next_cursor,
    )


@router.get("/{conversation_id}/history", response_model=ConversationHistoryResponseV1)
def get_conversation_history(
    conversation_id: str,
    request: Request,
    dependencies: ConversationRouteDependency,
    x_api_contract_version: str | None = Header(default=None),
) -> ConversationHistoryResponseV1:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(
        supported_version=dependencies.api_contract_version,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    history = dependencies.get_conversation_history_handler(
        GetConversationHistoryQuery(conversation_id=conversation_id)
    )
    if history is None:
        raise ApiRequestError(
            error_code="NOT_FOUND",
            user_message="대화를 찾을 수 없습니다.",
            status_code=404,
            request_id=request.state.request_id,
        )
    return ConversationHistoryResponseV1(
        conversation=ConversationItemV1(**asdict(history.conversation)),
        messages=[ConversationMessageV1(**asdict(item)) for item in history.messages],
        runs=[ConversationHistoryRunV1(**asdict(item)) for item in history.runs],
        truncated=history.truncated,
    )
