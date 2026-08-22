"""Runtime summary route."""

from fastapi import APIRouter, Header, Request

from google_work_agent.api.dependencies import RuntimeRouteDependency, enforce_access, enforce_supported_api_contract_version
from google_work_agent.api.schemas.runtime import RuntimeSummaryResponse
from google_work_agent.application.use_cases.runtime.get_runtime_summary import GetRuntimeSummaryHandler, GetRuntimeSummaryQuery
from google_work_agent.ports import EndpointPolicy

router = APIRouter(prefix="/api/v1")


@router.get("/runtime", response_model=RuntimeSummaryResponse)
def get_runtime(request: Request, dependencies: RuntimeRouteDependency, x_api_contract_version: str | None = Header(default=None)) -> RuntimeSummaryResponse:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(supported_version=dependencies.api_contract_version, request_id=request.state.request_id, request_version=x_api_contract_version)
    result = GetRuntimeSummaryHandler(query_service_factory=dependencies.query_service, safe_mode_state=dependencies.safe_mode_state).handle(GetRuntimeSummaryQuery())
    return RuntimeSummaryResponse(summary=result.summary, api_contract_version=dependencies.api_contract_version)
