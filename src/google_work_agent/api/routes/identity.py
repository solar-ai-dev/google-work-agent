"""Identity projection routes."""

from dataclasses import asdict

from fastapi import APIRouter, Header, Request

from google_work_agent.api.dependencies import (
    enforce_access,
    enforce_api_contract_version,
    get_container,
)
from google_work_agent.api.schemas.identity import CurrentGoogleAccountResponse
from google_work_agent.ports import EndpointPolicy

router = APIRouter(prefix="/api/v1")


@router.get("/identity/google-account", response_model=CurrentGoogleAccountResponse)
def get_current_google_account(
    request: Request,
    x_api_contract_version: str | None = Header(default=None),
) -> CurrentGoogleAccountResponse:
    container = get_container(request)
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_api_contract_version(
        container=container,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    account = container.query_service.get_current_google_account()
    return CurrentGoogleAccountResponse(
        account=None if account is None else asdict(account),
        api_contract_version=container.api_contract_version,
    )
