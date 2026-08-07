"""Runtime summary route."""

from fastapi import APIRouter, Header, Request

from google_work_agent.api.dependencies import (
    enforce_access,
    enforce_api_contract_version,
    get_container,
)
from google_work_agent.api.schemas.runtime import RuntimeSummaryResponse
from google_work_agent.ports import EndpointPolicy

router = APIRouter(prefix="/api/v1")


@router.get("/runtime", response_model=RuntimeSummaryResponse)
def get_runtime(
    request: Request,
    x_api_contract_version: str | None = Header(default=None),
) -> RuntimeSummaryResponse:
    container = get_container(request)
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_api_contract_version(
        container=container,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    summary = container.query_service.get_runtime_summary()
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
        },
        api_contract_version=container.api_contract_version,
    )
