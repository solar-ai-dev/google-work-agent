"""LLM credential routes over exact Application owners."""

from __future__ import annotations

from dataclasses import asdict
from typing import NoReturn

from fastapi import APIRouter, Header, Request

from google_work_agent.api.dependencies.access_control import enforce_access
from google_work_agent.api.dependencies.contract_version import (
    enforce_supported_api_contract_version,
)
from google_work_agent.api.dependencies.llm_connections import LLMRouteDependency
from google_work_agent.api.dependencies.runtime_operation import enforce_runtime_operation
from google_work_agent.api.errors.api_request_error import ApiRequestError
from google_work_agent.api.schemas.llm_connections.delete_llm_api_key import (
    DeleteLLMApiKeyRequest,
)
from google_work_agent.api.schemas.llm_connections.get_llm_connection import (
    LlmCredentialStatusV1,
)
from google_work_agent.api.schemas.llm_connections.store_llm_api_key import (
    StoreLLMApiKeyRequest,
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
from google_work_agent.application.use_cases.operational_replay import (
    OperationalCommandConflict,
    OperationalCommandUncertain,
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


@router.get("/credentials/llm/{provider}", response_model=LlmCredentialStatusV1)
def get_llm_connection(
    provider: str,
    request: Request,
    dependencies: LLMRouteDependency,
    x_api_contract_version: str | None = Header(default=None),
) -> LlmCredentialStatusV1:
    _contract(request, dependencies, x_api_contract_version)
    handler = dependencies.get_llm_credential_status_handler
    if not isinstance(handler, GetLlmCredentialStatusHandler):
        _raise_service_unavailable(request, "LLM_CREDENTIAL_STATUS_UNAVAILABLE")
    try:
        status = handler(GetLlmCredentialStatusQuery(provider=provider))
    except ValueError as error:
        _raise_invalid_credential_request(request, str(error))
    return LlmCredentialStatusV1.model_validate(asdict(status))


@router.put("/credentials/llm/{provider}", response_model=LlmCredentialStatusV1)
def store_llm_api_key(
    provider: str,
    payload: StoreLLMApiKeyRequest,
    request: Request,
    dependencies: LLMRouteDependency,
    x_api_contract_version: str | None = Header(default=None),
) -> LlmCredentialStatusV1:
    _contract(request, dependencies, x_api_contract_version)
    handler = dependencies.store_llm_credential_handler
    if not isinstance(handler, StoreLlmCredentialHandler):
        _raise_service_unavailable(request, "LLM_CREDENTIAL_STORE_UNAVAILABLE")
    try:
        result = handler(
            StoreLlmCredentialCommand(
                command_id=payload.command_id,
                provider=provider,
                secret=payload.api_key.encode("utf-8"),
                storage_mode=payload.storage_mode,
            )
        )
    except (OperationalCommandConflict, OperationalCommandUncertain) as error:
        _raise_operational_failure(error, request_id=request.state.request_id)
    except ValueError as error:
        _raise_invalid_credential_request(request, str(error))
    return LlmCredentialStatusV1.model_validate(asdict(result.status))


@router.delete("/credentials/llm/{provider}", response_model=LlmCredentialStatusV1)
def delete_llm_api_key(
    provider: str,
    payload: DeleteLLMApiKeyRequest,
    request: Request,
    dependencies: LLMRouteDependency,
    x_api_contract_version: str | None = Header(default=None),
) -> LlmCredentialStatusV1:
    _contract(request, dependencies, x_api_contract_version)
    handler = dependencies.delete_llm_credential_handler
    if not isinstance(handler, DeleteLlmCredentialHandler):
        _raise_service_unavailable(request, "LLM_CREDENTIAL_DELETE_UNAVAILABLE")
    try:
        result = handler(
            DeleteLlmCredentialCommand(command_id=payload.command_id, provider=provider)
        )
    except (OperationalCommandConflict, OperationalCommandUncertain) as error:
        _raise_operational_failure(error, request_id=request.state.request_id)
    except ValueError as error:
        _raise_invalid_credential_request(request, str(error))
    return LlmCredentialStatusV1.model_validate(asdict(result.status))


def _raise_service_unavailable(request: Request, detail_code: str) -> NoReturn:
    raise ApiRequestError(
        error_code="SERVICE_BUSY",
        user_message="The LLM credential service is not available.",
        status_code=503,
        request_id=request.state.request_id,
        detail_code=detail_code,
    )


def _raise_invalid_credential_request(request: Request, detail_code: str) -> NoReturn:
    raise ApiRequestError(
        error_code="INVALID_ARGUMENT",
        user_message="The LLM credential request is invalid.",
        status_code=422,
        request_id=request.state.request_id,
        detail_code=detail_code,
    )


def _raise_operational_failure(
    error: OperationalCommandConflict | OperationalCommandUncertain,
    *,
    request_id: str,
) -> NoReturn:
    conflict = isinstance(error, OperationalCommandConflict)
    raise ApiRequestError(
        error_code="CONFLICT" if conflict else "SERVICE_BUSY",
        user_message=(
            "The command identity conflicts with an earlier request."
            if conflict
            else "The previous credential operation result is not yet known."
        ),
        status_code=409 if conflict else 503,
        request_id=request_id,
        retryable=not conflict,
        detail_code="OPERATION_COMMAND_CONFLICT" if conflict else "OPERATION_RESULT_UNCERTAIN",
    ) from error


__all__ = ["router"]
