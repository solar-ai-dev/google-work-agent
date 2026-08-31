"""Runtime status and process-local requested-mode routes."""

from dataclasses import asdict
from typing import NoReturn

from fastapi import APIRouter, Header, Request

from google_work_agent.api.dependencies.access_control import enforce_access
from google_work_agent.api.dependencies.contract_version import (
    enforce_supported_api_contract_version,
)
from google_work_agent.api.dependencies.runtime_operation import enforce_runtime_operation
from google_work_agent.api.dependencies.runtime_summaries import RuntimeRouteDependency
from google_work_agent.api.errors.api_request_error import ApiRequestError
from google_work_agent.api.schemas.runtime_summaries.get_runtime_summary import (
    RuntimeDetailResponseV1,
    RuntimeModeStatusV1,
)
from google_work_agent.api.schemas.runtime_summaries.update_runtime_mode import (
    UpdateRuntimeModeRequest,
)
from google_work_agent.application.use_cases.operational_replay import (
    OperationalCommandConflict,
    OperationalCommandUncertain,
)
from google_work_agent.application.use_cases.runtime_mode.update_runtime_mode import (
    UpdateRuntimeModeCommand,
    UpdateRuntimeModeHandler,
)
from google_work_agent.application.use_cases.runtime_status.get_runtime_status import (
    GetRuntimeStatusHandler,
    GetRuntimeStatusQuery,
)
from google_work_agent.ports.system.api_access_port import EndpointPolicy

router = APIRouter(prefix="/api/v1")


@router.get("/runtime", response_model=RuntimeDetailResponseV1)
def get_runtime(
    request: Request,
    dependencies: RuntimeRouteDependency,
    x_api_contract_version: str | None = Header(default=None),
) -> RuntimeDetailResponseV1:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(
        supported_version=dependencies.api_contract_version,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    handler = dependencies.get_runtime_status_handler
    if not isinstance(handler, GetRuntimeStatusHandler):
        _raise_service_unavailable(request, "RUNTIME_STATUS_UNAVAILABLE")
    result = handler(GetRuntimeStatusQuery(session_established=True))
    return RuntimeDetailResponseV1.model_validate(asdict(result))


@router.post("/runtime/mode", response_model=RuntimeModeStatusV1)
def update_runtime_mode(
    payload: UpdateRuntimeModeRequest,
    request: Request,
    dependencies: RuntimeRouteDependency,
    x_api_contract_version: str | None = Header(default=None),
) -> RuntimeModeStatusV1:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(
        supported_version=dependencies.api_contract_version,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    enforce_runtime_operation(request, operation="SETTINGS")
    handler = dependencies.update_runtime_mode_handler
    if not isinstance(handler, UpdateRuntimeModeHandler):
        _raise_service_unavailable(request, "RUNTIME_MODE_UPDATE_UNAVAILABLE")
    try:
        result = handler(
            UpdateRuntimeModeCommand(
                command_id=payload.command_id,
                requested_mode=payload.requested_mode,
            )
        )
    except (OperationalCommandConflict, OperationalCommandUncertain) as error:
        _raise_operational_failure(error, request_id=request.state.request_id)
    except RuntimeError as error:
        if str(error) == "RUNTIME_MODE_CHANGE_BLOCKED_BY_ACTIVE_RUN":
            raise ApiRequestError(
                error_code="CONFLICT",
                user_message="Runtime mode cannot change while a Run is active.",
                status_code=409,
                request_id=request.state.request_id,
                detail_code="RUNTIME_MODE_ACTIVE_RUN",
            ) from error
        raise
    return RuntimeModeStatusV1(
        schema_version=1,
        requested_mode=result.requested_mode,
        actual_runtime=None,
        fallback_reason=None,
    )


def _raise_service_unavailable(request: Request, detail_code: str) -> NoReturn:
    raise ApiRequestError(
        error_code="SERVICE_BUSY",
        user_message="The runtime service is not available.",
        status_code=503,
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
            else "The previous runtime-mode operation result is not yet known."
        ),
        status_code=409 if conflict else 503,
        request_id=request_id,
        retryable=not conflict,
        detail_code="OPERATION_COMMAND_CONFLICT" if conflict else "OPERATION_RESULT_UNCERTAIN",
    ) from error


__all__ = ["router"]
