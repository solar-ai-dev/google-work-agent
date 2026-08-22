"""Identity projection routes."""

from fastapi import APIRouter, Header, Request

from google_work_agent.api.dependencies.access_control import enforce_access
from google_work_agent.api.dependencies.contract_version import (
    enforce_supported_api_contract_version,
)
from google_work_agent.api.dependencies.identities import IdentityRouteDependency
from google_work_agent.api.schemas.identities.get_google_account import CurrentGoogleAccountResponse
from google_work_agent.application.use_cases.identity.get_google_account import (
    GetGoogleAccountHandler,
    GetGoogleAccountQuery,
)
from google_work_agent.ports import EndpointPolicy

router = APIRouter(prefix="/api/v1")


@router.get("/identity/google-account", response_model=CurrentGoogleAccountResponse)
def get_current_google_account(
    request: Request,
    dependencies: IdentityRouteDependency,
    x_api_contract_version: str | None = Header(default=None),
) -> CurrentGoogleAccountResponse:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(
        supported_version=dependencies.api_contract_version,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    result = GetGoogleAccountHandler(query_service_factory=dependencies.query_service).handle(
        GetGoogleAccountQuery()
    )
    return CurrentGoogleAccountResponse(
        account=result.account, api_contract_version=dependencies.api_contract_version
    )
