"""LLM connection and credential routes."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Header, Request

from google_work_agent.api.dependencies.access_control import enforce_access
from google_work_agent.api.dependencies.contract_version import (
    enforce_supported_api_contract_version,
)
from google_work_agent.api.dependencies.llm_connections import LLMRouteDependency
from google_work_agent.api.dependencies.runtime_operation import enforce_runtime_operation
from google_work_agent.api.errors.api_request_error import ApiRequestError
from google_work_agent.api.schemas.llm_connections.delete_llm_api_key import DeleteLLMApiKeyResponse
from google_work_agent.api.schemas.llm_connections.get_llm_connection import LLMConnectionResponse
from google_work_agent.api.schemas.llm_connections.store_llm_api_key import (
    StoreLLMApiKeyRequest,
    StoreLLMApiKeyResponse,
)
from google_work_agent.api.schemas.llm_connections.test_llm_connection import (
    TestLLMConnectionResponse,
)
from google_work_agent.application.use_cases.llm.test_llm_connection import (
    TestLLMConnectionCommand,
    TestLLMConnectionHandler,
)
from google_work_agent.application.use_cases.llm_credential.delete_llm_credential import (
    DeleteLlmCredentialCommand,
    DeleteLlmCredentialHandler,
)
from google_work_agent.application.use_cases.llm_credential.get_llm_credential_status import (
    GetLlmCredentialStatusHandler,
    GetLlmCredentialStatusQuery,
)
from google_work_agent.application.use_cases.llm_credential.store_llm_credential import (
    StoreLlmCredentialCommand,
    StoreLlmCredentialHandler,
)
from google_work_agent.ports.system.api_access_port import EndpointPolicy

router = APIRouter(prefix="/api/v1")


def _contract(request: Request, dependencies: LLMRouteDependency, version: str | None) -> None:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(
        supported_version=dependencies.api_contract_version,
        request_id=request.state.request_id,
        request_version=version,
    )
    enforce_runtime_operation(request, operation="SETTINGS")


@router.get("/credentials/llm/{provider}", response_model=LLMConnectionResponse)
def get_llm_connection(
    provider: str,
    request: Request,
    dependencies: LLMRouteDependency,
    x_api_contract_version: str | None = Header(default=None),
) -> LLMConnectionResponse:
    _contract(request, dependencies, x_api_contract_version)
    try:
        handler = dependencies.get_llm_credential_status_handler()
        if not isinstance(handler, GetLlmCredentialStatusHandler):
            raise RuntimeError("LLM_CREDENTIAL_STATUS_UNAVAILABLE")
        status = handler(GetLlmCredentialStatusQuery(provider=provider))
    except RuntimeError as error:
        raise _service_unavailable(request, str(error)) from error
    return LLMConnectionResponse(
        llm=asdict(status), api_contract_version=dependencies.api_contract_version
    )


@router.put("/credentials/llm/{provider}", response_model=StoreLLMApiKeyResponse)
def store_llm_api_key(
    provider: str,
    payload: StoreLLMApiKeyRequest,
    request: Request,
    dependencies: LLMRouteDependency,
    x_api_contract_version: str | None = Header(default=None),
) -> StoreLLMApiKeyResponse:
    _contract(request, dependencies, x_api_contract_version)
    try:
        handler = dependencies.store_llm_credential_handler()
        if not isinstance(handler, StoreLlmCredentialHandler):
            raise RuntimeError("LLM_CREDENTIAL_STORE_UNAVAILABLE")
        result = handler(
            StoreLlmCredentialCommand(
                command_id=request.state.request_id,
                provider=provider,
                secret=payload.api_key.encode("utf-8"),
                storage_mode=payload.storage_mode,
            )
        )
    except RuntimeError as error:
        raise _service_unavailable(request, str(error)) from error
    except ValueError as error:
        raise ApiRequestError(
            error_code="INVALID_ARGUMENT",
            user_message=str(error),
            status_code=422,
            request_id=request.state.request_id,
            detail_code="LLM_CREDENTIAL_INVALID",
        ) from error
    return StoreLLMApiKeyResponse(
        credential_state=result.status.validation_status,
        api_contract_version=dependencies.api_contract_version,
    )


@router.delete("/credentials/llm/{provider}", response_model=DeleteLLMApiKeyResponse)
def delete_llm_api_key(
    provider: str,
    request: Request,
    dependencies: LLMRouteDependency,
    x_api_contract_version: str | None = Header(default=None),
) -> DeleteLLMApiKeyResponse:
    _contract(request, dependencies, x_api_contract_version)
    try:
        handler = dependencies.delete_llm_credential_handler()
        if not isinstance(handler, DeleteLlmCredentialHandler):
            raise RuntimeError("LLM_CREDENTIAL_DELETE_UNAVAILABLE")
        result = handler(
            DeleteLlmCredentialCommand(
                command_id=request.state.request_id,
                provider=provider,
            )
        )
    except RuntimeError as error:
        raise _service_unavailable(request, str(error)) from error
    return DeleteLLMApiKeyResponse(
        credential_state=result.status.validation_status,
        api_contract_version=dependencies.api_contract_version,
    )


@router.post("/llm/test", response_model=TestLLMConnectionResponse)
def test_llm_connection(
    request: Request,
    dependencies: LLMRouteDependency,
    x_api_contract_version: str | None = Header(default=None),
) -> TestLLMConnectionResponse:
    _contract(request, dependencies, x_api_contract_version)
    try:
        result = TestLLMConnectionHandler(
            service_factory=dependencies.test_llm_connection_service
        ).handle(TestLLMConnectionCommand())
    except RuntimeError as error:
        raise _service_unavailable(request, str(error)) from error
    except Exception as error:
        if isinstance(error, ApiRequestError):
            raise
        raise ApiRequestError(
            error_code="SERVICE_BUSY",
            user_message=str(error),
            status_code=409,
            request_id=request.state.request_id,
            detail_code="LLM_TEST_FAILED",
        ) from error
    return TestLLMConnectionResponse(
        llm=result.llm, api_contract_version=dependencies.api_contract_version
    )


def _service_unavailable(request: Request, detail_code: str) -> ApiRequestError:
    return ApiRequestError(
        error_code="SERVICE_BUSY",
        user_message="서비스가 아직 준비되지 않았습니다.",
        status_code=503,
        request_id=request.state.request_id,
        detail_code=detail_code,
    )
