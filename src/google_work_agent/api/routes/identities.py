"""Identity projection routes."""

from fastapi import APIRouter, Header, Request

from google_work_agent.api.dependencies.access_control import enforce_access
from google_work_agent.api.dependencies.contract_version import (
    enforce_supported_api_contract_version,
)
from google_work_agent.api.dependencies.identities import IdentityRouteDependency
from google_work_agent.api.schemas.identities.get_google_account import CurrentGoogleAccountResponse
from google_work_agent.application.use_cases.connection.get_connection_status import (
    GetConnectionStatusHandler,
    GetConnectionStatusQuery,
)
from google_work_agent.ports.system.api_access_port import EndpointPolicy

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
    handler = dependencies.get_connection_status_handler
    account = None
    if isinstance(handler, GetConnectionStatusHandler):
        connection = handler(GetConnectionStatusQuery(connector_id="google_workspace")).connection
        if connection.account_id is not None or connection.display_email is not None:
            account = {
                "account_id": connection.account_id,
                "email": connection.display_email,
                "display_name": None,
            }
    return CurrentGoogleAccountResponse(
        account=account, api_contract_version=dependencies.api_contract_version
    )
