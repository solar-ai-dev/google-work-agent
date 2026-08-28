"""Runtime status and requested-mode routes."""

from dataclasses import asdict

from fastapi import APIRouter, Header, Request

from google_work_agent.api.dependencies.access_control import enforce_access
from google_work_agent.api.dependencies.contract_version import (
    enforce_supported_api_contract_version,
)
from google_work_agent.api.dependencies.runtime_summaries import RuntimeRouteDependency
from google_work_agent.api.schemas.runtime_summaries.get_runtime_summary import (
    RuntimeSummaryResponse,
)
from google_work_agent.api.schemas.runtime_summaries.update_runtime_mode import (
    UpdateRuntimeModeRequest,
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


@router.get("/runtime", response_model=RuntimeSummaryResponse)
def get_runtime(
    request: Request,
    dependencies: RuntimeRouteDependency,
    x_api_contract_version: str | None = Header(default=None),
) -> RuntimeSummaryResponse:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(
        supported_version=dependencies.api_contract_version,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    try:
        handler = dependencies.get_runtime_status_handler()
    except RuntimeError:
        handler = None
    if not isinstance(handler, GetRuntimeStatusHandler):
        safe_mode = dependencies.safe_mode_state()
        if safe_mode is None or not safe_mode.enabled:
            raise RuntimeError("RUNTIME_STATUS_UNAVAILABLE")
        return RuntimeSummaryResponse(
            summary={
                "safe_mode": True,
                "safe_mode_reason_codes": list(safe_mode.reason_codes),
                "safe_mode_allowed_operations": list(safe_mode.allowed_operations),
            },
            api_contract_version=dependencies.api_contract_version,
        )
    result = handler(GetRuntimeStatusQuery())
    summary = asdict(result)
    safe_mode = dependencies.safe_mode_state()
    summary.update(
        {
            "safe_mode": bool(safe_mode and safe_mode.enabled),
            "safe_mode_reason_codes": [] if safe_mode is None else list(safe_mode.reason_codes),
            "safe_mode_allowed_operations": []
            if safe_mode is None
            else list(safe_mode.allowed_operations),
        }
    )
    return RuntimeSummaryResponse(
        summary=summary,
        api_contract_version=dependencies.api_contract_version,
    )


@router.post("/runtime/mode", response_model=RuntimeSummaryResponse)
def update_runtime_mode(
    payload: UpdateRuntimeModeRequest,
    request: Request,
    dependencies: RuntimeRouteDependency,
    x_api_contract_version: str | None = Header(default=None),
) -> RuntimeSummaryResponse:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(
        supported_version=dependencies.api_contract_version,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    handler = dependencies.update_runtime_mode_handler()
    status_handler = dependencies.get_runtime_status_handler()
    if not isinstance(handler, UpdateRuntimeModeHandler) or not isinstance(
        status_handler, GetRuntimeStatusHandler
    ):
        raise RuntimeError("RUNTIME_MODE_UPDATE_UNAVAILABLE")
    handler(
        UpdateRuntimeModeCommand(
            command_id=payload.command_id,
            requested_mode=payload.requested_mode,
        )
    )
    return RuntimeSummaryResponse(
        summary=asdict(status_handler(GetRuntimeStatusQuery())),
        api_contract_version=dependencies.api_contract_version,
    )
