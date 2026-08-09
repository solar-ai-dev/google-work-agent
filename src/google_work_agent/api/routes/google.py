"""Google connection routes."""

from fastapi import APIRouter, Header, Request

from google_work_agent.api.dependencies import (
    enforce_access,
    enforce_api_contract_version,
    get_container,
)
from google_work_agent.api.errors import ApiError
from google_work_agent.api.schemas.google import (
    GoogleConnectionResponse,
    GoogleDisconnectResponse,
    GoogleOAuthStartResponse,
)
from google_work_agent.ports import EndpointPolicy
from google_work_agent.ports.mcp_transport import MCPTransportError, MCPTransportErrorCode

router = APIRouter(prefix="/api/v1/google")


@router.post("/oauth/start", response_model=GoogleOAuthStartResponse)
def start_google_oauth(
    request: Request,
    x_api_contract_version: str | None = Header(default=None),
) -> GoogleOAuthStartResponse:
    container = get_container(request)
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_api_contract_version(
        container=container,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    service = container.start_google_oauth_service
    if service is None:
        raise ApiError(
            error_code="SERVICE_BUSY",
            user_message="Google OAuth provider is not configured.",
            status_code=503,
            request_id=request.state.request_id,
            detail_code="GOOGLE_OAUTH_UNAVAILABLE",
        )
    try:
        result = service()
    except MCPTransportError as error:
        if error.code is not MCPTransportErrorCode.CONFIGURATION_ERROR:
            raise
        if str(error) == "GOOGLE_OAUTH_CLIENT_SECRET_MISSING":
            raise ApiError(
                error_code="CONFIGURATION_ERROR",
                user_message="Set GOOGLE_OAUTH_CLIENT_SECRET in .env.local.",
                status_code=503,
                request_id=request.state.request_id,
                detail_code="GOOGLE_OAUTH_CLIENT_SECRET_MISSING",
            ) from error
        raise ApiError(
            error_code="CONFIGURATION_ERROR",
            user_message="Set GOOGLE_OAUTH_CLIENT_ID in .env.local.",
            status_code=503,
            request_id=request.state.request_id,
            detail_code="GOOGLE_OAUTH_CLIENT_ID_MISSING",
        ) from error
    return GoogleOAuthStartResponse(
        flow_id=result.flow_id,
        authorization_url=result.authorization_url,
        callback_url=result.callback_url,
        expires_at_ms=result.expires_at_ms,
        oauth_environment=result.oauth_environment.value,
        scopes=list(result.scopes),
        api_contract_version=container.api_contract_version,
    )


@router.get("/connection", response_model=GoogleConnectionResponse)
def get_google_connection(
    request: Request,
    x_api_contract_version: str | None = Header(default=None),
) -> GoogleConnectionResponse:
    container = get_container(request)
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_api_contract_version(
        container=container,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    service = container.get_google_connection_service
    if service is None:
        raise ApiError(
            error_code="SERVICE_BUSY",
            user_message="Google connection provider is not configured.",
            status_code=503,
            request_id=request.state.request_id,
            detail_code="GOOGLE_CONNECTION_UNAVAILABLE",
        )
    result = service()
    return GoogleConnectionResponse(
        connected=result.connected,
        credential_state=result.credential_state.value,
        account_email=result.account_email,
        display_name=result.display_name,
        granted_scopes=list(result.granted_scopes),
        missing_scopes=list(result.missing_scopes),
        reauth_required=result.reauth_required,
        oauth_environment=result.oauth_environment.value,
        last_checked_at_ms=result.last_checked_at_ms,
        safe_error_code=result.safe_error_code,
        safe_error_description=result.safe_error_description,
        api_contract_version=container.api_contract_version,
    )


@router.post("/disconnect", response_model=GoogleDisconnectResponse)
def disconnect_google(
    request: Request,
    x_api_contract_version: str | None = Header(default=None),
) -> GoogleDisconnectResponse:
    container = get_container(request)
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_api_contract_version(
        container=container,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    service = container.disconnect_google_service
    if service is None:
        raise ApiError(
            error_code="SERVICE_BUSY",
            user_message="Google disconnect provider is not configured.",
            status_code=503,
            request_id=request.state.request_id,
            detail_code="GOOGLE_DISCONNECT_UNAVAILABLE",
        )
    result = service()
    return GoogleDisconnectResponse(
        disconnected=result.disconnected,
        credential_deleted=result.credential_deleted,
        revoke_attempted=result.revoke_attempted,
        revoke_succeeded=result.revoke_succeeded,
        credential_state=result.credential_state.value,
        api_contract_version=container.api_contract_version,
    )
