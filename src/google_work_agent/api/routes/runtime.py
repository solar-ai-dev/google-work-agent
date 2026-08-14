"""Runtime summary route."""

from fastapi import APIRouter, Header, Request

from google_work_agent.api.dependencies import (
    RuntimeRouteDependency,
    enforce_access,
    enforce_supported_api_contract_version,
)
from google_work_agent.api.schemas.runtime import RuntimeSummaryResponse
from google_work_agent.ports import EndpointPolicy

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
    summary = dependencies.query_service().get_runtime_summary()
    safe_mode = summary.safe_mode
    safe_mode_reason_codes = list(summary.safe_mode_reason_codes)
    allowed_operations = list(summary.allowed_operations)
    state = dependencies.safe_mode_state()
    if state is not None:
        safe_mode = state.enabled
        safe_mode_reason_codes = list(state.reason_codes)
        allowed_operations = list(state.allowed_operations)
    return RuntimeSummaryResponse(
        summary={
            "google": summary.google,
            "mcp": summary.mcp,
            "api_llm": summary.api_llm,
            "ollama": summary.ollama,
            "deployment_profile": summary.deployment_profile,
            "recovery_required_run_ids": list(summary.recovery_required_run_ids),
            "open_run_ids": list(summary.open_run_ids),
            "google_connection": summary.google_connection,
            "mcp_runtime": summary.mcp_runtime,
            "llm": summary.llm,
            "safe_mode": safe_mode,
            "safe_mode_reason_codes": safe_mode_reason_codes,
            "allowed_operations": allowed_operations,
        },
        api_contract_version=dependencies.api_contract_version,
    )
