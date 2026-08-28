"""Sanitized diagnostic bundle command route."""

from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Header, Request

from google_work_agent.api.dependencies.access_control import enforce_access
from google_work_agent.api.dependencies.contract_version import (
    enforce_supported_api_contract_version,
)
from google_work_agent.api.dependencies.diagnostics import DiagnosticRouteDependency
from google_work_agent.api.schemas.model import ApiModel
from google_work_agent.application.use_cases.diagnostic_bundle.create_diagnostic_bundle import (
    CreateDiagnosticBundleCommand,
    CreateDiagnosticBundleHandler,
)
from google_work_agent.ports.system.api_access_port import EndpointPolicy

router = APIRouter(prefix="/api/v1")


class CreateDiagnosticBundleRequest(ApiModel):
    command_id: str
    scope: Literal["LAST_24H", "RUN"]
    run_id: str | None = None


class DiagnosticBundleResponse(ApiModel):
    bundle: dict[str, object]
    api_contract_version: str


@router.post("/diagnostics/bundles", response_model=DiagnosticBundleResponse)
def create_diagnostic_bundle(
    payload: CreateDiagnosticBundleRequest,
    request: Request,
    dependencies: DiagnosticRouteDependency,
    x_api_contract_version: str | None = Header(default=None),
) -> DiagnosticBundleResponse:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(
        supported_version=dependencies.api_contract_version,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    handler = dependencies.create_diagnostic_bundle_handler
    if not isinstance(handler, CreateDiagnosticBundleHandler):
        raise RuntimeError("DIAGNOSTIC_BUNDLE_UNAVAILABLE")
    result = handler(
        CreateDiagnosticBundleCommand(
            command_id=payload.command_id,
            scope=payload.scope,
            run_id=payload.run_id,
        )
    )
    return DiagnosticBundleResponse(
        bundle=asdict(result.bundle),
        api_contract_version=dependencies.api_contract_version,
    )


__all__ = ["router"]
