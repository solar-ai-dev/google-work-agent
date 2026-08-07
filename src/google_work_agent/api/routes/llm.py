"""LLM runtime and credential routes."""

from __future__ import annotations

from fastapi import APIRouter, Header, Request

from google_work_agent.adapters.llm import CredentialStorageMode
from google_work_agent.adapters.runtime import RuntimeOperation
from google_work_agent.api.dependencies import (
    enforce_access,
    enforce_api_contract_version,
    enforce_runtime_operation,
    get_container,
)
from google_work_agent.api.errors import ApiError
from google_work_agent.api.schemas.llm import (
    DeleteLLMApiKeyResponse,
    LLMConnectionResponse,
    StoreLLMApiKeyRequest,
    StoreLLMApiKeyResponse,
    TestLLMConnectionResponse,
)
from google_work_agent.ports import EndpointPolicy

router = APIRouter(prefix="/api/v1")


@router.get("/llm/connection", response_model=LLMConnectionResponse)
def get_llm_connection(
    request: Request,
    x_api_contract_version: str | None = Header(default=None),
) -> LLMConnectionResponse:
    container = get_container(request)
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_api_contract_version(
        container=container,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    enforce_runtime_operation(request, operation=RuntimeOperation.SETTINGS)
    service = container.get_llm_connection_service
    if service is None:
        raise _service_unavailable(request, "LLM_CONNECTION_UNAVAILABLE")
    return LLMConnectionResponse(
        llm=service(),
        api_contract_version=container.api_contract_version,
    )


@router.post("/llm/api-key", response_model=StoreLLMApiKeyResponse)
def store_llm_api_key(
    payload: StoreLLMApiKeyRequest,
    request: Request,
    x_api_contract_version: str | None = Header(default=None),
) -> StoreLLMApiKeyResponse:
    container = get_container(request)
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_api_contract_version(
        container=container,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    enforce_runtime_operation(request, operation=RuntimeOperation.SETTINGS)
    service = container.store_llm_api_key_service
    if service is None:
        raise _service_unavailable(request, "LLM_CREDENTIAL_UNAVAILABLE")
    try:
        result = service(
            api_key=payload.api_key,
            storage_mode=CredentialStorageMode(payload.storage_mode),
        )
    except ValueError as error:
        raise ApiError(
            error_code="INVALID_ARGUMENT",
            user_message=str(error),
            status_code=422,
            request_id=request.state.request_id,
            detail_code="LLM_CREDENTIAL_INVALID",
        ) from error
    return StoreLLMApiKeyResponse(
        credential_state=str(result["credential_state"]),
        api_contract_version=container.api_contract_version,
    )


@router.delete("/llm/api-key", response_model=DeleteLLMApiKeyResponse)
def delete_llm_api_key(
    request: Request,
    x_api_contract_version: str | None = Header(default=None),
) -> DeleteLLMApiKeyResponse:
    container = get_container(request)
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_api_contract_version(
        container=container,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    enforce_runtime_operation(request, operation=RuntimeOperation.SETTINGS)
    service = container.delete_llm_api_key_service
    if service is None:
        raise _service_unavailable(request, "LLM_CREDENTIAL_UNAVAILABLE")
    result = service()
    return DeleteLLMApiKeyResponse(
        credential_state=str(result["credential_state"]),
        api_contract_version=container.api_contract_version,
    )


@router.post("/llm/test", response_model=TestLLMConnectionResponse)
def test_llm_connection(
    request: Request,
    x_api_contract_version: str | None = Header(default=None),
) -> TestLLMConnectionResponse:
    container = get_container(request)
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_api_contract_version(
        container=container,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    enforce_runtime_operation(request, operation=RuntimeOperation.SETTINGS)
    service = container.test_llm_connection_service
    if service is None:
        raise _service_unavailable(request, "LLM_TEST_UNAVAILABLE")
    try:
        result = service()
    except Exception as error:
        if isinstance(error, ApiError):
            raise
        raise ApiError(
            error_code="SERVICE_BUSY",
            user_message=str(error),
            status_code=409,
            request_id=request.state.request_id,
            detail_code="LLM_TEST_FAILED",
        ) from error
    return TestLLMConnectionResponse(
        llm=result,
        api_contract_version=container.api_contract_version,
    )


def _service_unavailable(request: Request, detail_code: str) -> ApiError:
    return ApiError(
        error_code="SERVICE_BUSY",
        user_message="서비스가 아직 준비되지 않았습니다.",
        status_code=503,
        request_id=request.state.request_id,
        detail_code=detail_code,
    )
