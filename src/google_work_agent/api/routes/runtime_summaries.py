"""Runtime status and requested-mode routes."""

from dataclasses import asdict
from typing import cast

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
    RuntimeModeStatus,
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
            schema_version=1,
            service_instance_id="unavailable",
            connectors=[],
            llm_providers=[],
            component_circuits=[],
            active_run_budget=None,
            recovery_required=True,
            release_version="unavailable",
            frontend_build_version="unavailable",
            api_contract_version=dependencies.api_contract_version,
            deployment_profile="unavailable",
            runtime_mode=RuntimeModeStatus(
                schema_version=1,
                requested_mode="AUTO",
                actual_runtime=None,
                fallback_reason=None,
            ),
            database_status="UNAVAILABLE",
            migration_status="FAILED",
            sse_status="UNAVAILABLE",
            recent_sanitized_error_code=(
                safe_mode.reason_codes[0] if safe_mode.reason_codes else None
            ),
            launcher_status="DEGRADED",
            manifest_status="UNAVAILABLE",
            session_status="ESTABLISHED",
            safe_mode=True,
            last_backup_status=None,
            last_migration_status=None,
        )
    result = handler(GetRuntimeStatusQuery())
    summary = asdict(result)
    safe_mode = dependencies.safe_mode_state()
    summary["safe_mode"] = bool(safe_mode and safe_mode.enabled)
    summary["session_status"] = "ESTABLISHED"
    return cast(RuntimeSummaryResponse, RuntimeSummaryResponse.model_validate(summary))


@router.post("/runtime/mode", response_model=RuntimeModeStatus)
def update_runtime_mode(
    payload: UpdateRuntimeModeRequest,
    request: Request,
    dependencies: RuntimeRouteDependency,
    x_api_contract_version: str | None = Header(default=None),
) -> RuntimeModeStatus:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(
        supported_version=dependencies.api_contract_version,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    handler = dependencies.update_runtime_mode_handler()
    if not isinstance(handler, UpdateRuntimeModeHandler):
        raise RuntimeError("RUNTIME_MODE_UPDATE_UNAVAILABLE")
    result = handler(
        UpdateRuntimeModeCommand(
            command_id=payload.command_id,
            requested_mode=payload.requested_mode,
        )
    )
    return RuntimeModeStatus(
        schema_version=1,
        requested_mode=result.requested_mode,
        actual_runtime=None,
        fallback_reason=None,
    )
