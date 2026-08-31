"""Sanitized diagnostic bundle command route."""

from dataclasses import asdict
from typing import NoReturn

from fastapi import APIRouter, Header, Request

from google_work_agent.api.dependencies.access_control import enforce_access
from google_work_agent.api.dependencies.contract_version import (
    enforce_supported_api_contract_version,
)
from google_work_agent.api.dependencies.diagnostics import DiagnosticRouteDependency
from google_work_agent.api.dependencies.runtime_operation import enforce_runtime_operation
from google_work_agent.api.errors.api_request_error import ApiRequestError
from google_work_agent.api.schemas.diagnostics.create_diagnostic_bundle import (
    CreateDiagnosticBundleRequestV1,
    DiagnosticBundleMetadataResponseV1,
)
from google_work_agent.application.use_cases.diagnostic_bundle.create_diagnostic_bundle import (
    CreateDiagnosticBundleCommand,
    CreateDiagnosticBundleHandler,
)
from google_work_agent.application.use_cases.operational_replay import (
    OperationalCommandConflict,
    OperationalCommandUncertain,
)
from google_work_agent.ports.system.api_access_port import EndpointPolicy

router = APIRouter(prefix="/api/v1")


@router.post(
    "/diagnostics/bundles",
    response_model=DiagnosticBundleMetadataResponseV1,
)
def create_diagnostic_bundle(
    payload: CreateDiagnosticBundleRequestV1,
    request: Request,
    dependencies: DiagnosticRouteDependency,
    x_api_contract_version: str | None = Header(default=None),
) -> DiagnosticBundleMetadataResponseV1:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(
        supported_version=dependencies.api_contract_version,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    enforce_runtime_operation(request, operation="DIAGNOSTICS")
    handler = dependencies.create_diagnostic_bundle_handler
    if not isinstance(handler, CreateDiagnosticBundleHandler):
        raise ApiRequestError(
            error_code="SERVICE_BUSY",
            user_message="The diagnostic bundle service is not available.",
            status_code=503,
            request_id=request.state.request_id,
            detail_code="DIAGNOSTIC_BUNDLE_UNAVAILABLE",
        )
    try:
        result = handler(
            CreateDiagnosticBundleCommand(
                command_id=payload.command_id,
                scope=payload.scope,
                run_id=payload.run_id,
            )
        )
    except (OperationalCommandConflict, OperationalCommandUncertain) as error:
        _raise_operational_failure(error, request_id=request.state.request_id)
    except ValueError as error:
        raise ApiRequestError(
            error_code="INVALID_ARGUMENT",
            user_message="The diagnostic bundle request is invalid.",
            status_code=422,
            request_id=request.state.request_id,
            detail_code="DIAGNOSTIC_BUNDLE_INVALID",
        ) from error
    return DiagnosticBundleMetadataResponseV1.model_validate(asdict(result.bundle))


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
            else "The previous diagnostic operation result is not yet known."
        ),
        status_code=409 if conflict else 503,
        request_id=request_id,
        retryable=not conflict,
        detail_code="OPERATION_COMMAND_CONFLICT" if conflict else "OPERATION_RESULT_UNCERTAIN",
    ) from error


__all__ = ["router"]
