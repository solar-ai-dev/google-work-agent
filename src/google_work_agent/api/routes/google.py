"""Google connector connection routes over canonical Application use cases."""

from fastapi import APIRouter, Header, Request

from google_work_agent.api.dependencies import (
    GoogleRouteDependency,
    enforce_access,
    enforce_supported_api_contract_version,
)
from google_work_agent.api.errors import ApiError
from google_work_agent.api.schemas.google import (
    GoogleConnectionResponse,
    GoogleDisconnectResponse,
    GoogleOAuthStartResponse,
)
from google_work_agent.application.ports.connector_failure import (
    ConnectorFailureCode,
    ConnectorOperationFailure,
)
from google_work_agent.application.use_cases.connector_connection.disconnect_connector import (
    DisconnectConnectorCommand,
    DisconnectConnectorHandler,
)
from google_work_agent.application.use_cases.connector_connection.get_connection import (
    GetConnectionHandler,
    GetConnectionQuery,
)
from google_work_agent.application.use_cases.connector_connection.start_oauth import (
    StartOAuthCommand,
    StartOAuthHandler,
)
from google_work_agent.ports import EndpointPolicy

router = APIRouter(prefix="/api/v1/google")


@router.post("/oauth/start", response_model=GoogleOAuthStartResponse)
def start_google_oauth(
    request: Request,
    dependencies: GoogleRouteDependency,
    x_api_contract_version: str | None = Header(default=None),
) -> GoogleOAuthStartResponse:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(
        supported_version=dependencies.api_contract_version,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    service = dependencies.start_google_oauth_service()
    if service is None:
        raise ApiError(
            error_code="SERVICE_BUSY",
            user_message="Google OAuth provider is not configured.",
            status_code=503,
            request_id=request.state.request_id,
            detail_code="GOOGLE_OAUTH_UNAVAILABLE",
        )
    try:
        result = StartOAuthHandler(service)(StartOAuthCommand()).oauth
    except ConnectorOperationFailure as error:
        _raise_google_failure(error, request_id=request.state.request_id)
    return GoogleOAuthStartResponse(
        flow_id=result.flow_id,
        authorization_url=result.authorization_url,
        callback_url=result.callback_url,
        expires_at_ms=result.expires_at_ms,
        oauth_environment=result.oauth_environment.value,
        scopes=list(result.scopes),
        api_contract_version=dependencies.api_contract_version,
    )


@router.get("/connection", response_model=GoogleConnectionResponse)
def get_google_connection(
    request: Request,
    dependencies: GoogleRouteDependency,
    x_api_contract_version: str | None = Header(default=None),
) -> GoogleConnectionResponse:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(
        supported_version=dependencies.api_contract_version,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    service = dependencies.get_google_connection_service()
    if service is None:
        raise ApiError(
            error_code="SERVICE_BUSY",
            user_message="Google connection provider is not configured.",
            status_code=503,
            request_id=request.state.request_id,
            detail_code="GOOGLE_CONNECTION_UNAVAILABLE",
        )
    try:
        result = GetConnectionHandler(service)(GetConnectionQuery()).connection
    except ConnectorOperationFailure as error:
        _raise_google_failure(error, request_id=request.state.request_id)
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
        api_contract_version=dependencies.api_contract_version,
    )


@router.post("/disconnect", response_model=GoogleDisconnectResponse)
def disconnect_google(
    request: Request,
    dependencies: GoogleRouteDependency,
    x_api_contract_version: str | None = Header(default=None),
) -> GoogleDisconnectResponse:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(
        supported_version=dependencies.api_contract_version,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    service = dependencies.disconnect_google_service()
    if service is None:
        raise ApiError(
            error_code="SERVICE_BUSY",
            user_message="Google disconnect provider is not configured.",
            status_code=503,
            request_id=request.state.request_id,
            detail_code="GOOGLE_DISCONNECT_UNAVAILABLE",
        )
    try:
        result = DisconnectConnectorHandler(service)(DisconnectConnectorCommand()).disconnect
    except ConnectorOperationFailure as error:
        _raise_google_failure(error, request_id=request.state.request_id)
    return GoogleDisconnectResponse(
        disconnected=result.disconnected,
        credential_deleted=result.credential_deleted,
        revoke_attempted=result.revoke_attempted,
        revoke_succeeded=result.revoke_succeeded,
        credential_state=result.credential_state.value,
        api_contract_version=dependencies.api_contract_version,
    )


def _raise_google_failure(error: ConnectorOperationFailure, *, request_id: str) -> None:
    if error.code is ConnectorFailureCode.CONFIGURATION_ERROR:
        if error.detail_code == "GOOGLE_OAUTH_CLIENT_SECRET_MISSING":
            user_message = "Google OAuth client secret is not configured."
        elif error.detail_code == "GOOGLE_OAUTH_CLIENT_ID_MISSING":
            user_message = "Google OAuth client ID is not configured."
        else:
            user_message = "Google connector configuration is invalid."
        raise ApiError(
            error_code="CONFIGURATION_ERROR",
            user_message=user_message,
            status_code=503,
            request_id=request_id,
            retryable=False,
            detail_code=error.detail_code,
        ) from error

    mapping = {
        ConnectorFailureCode.INVALID_ARGUMENT: ("INVALID_ARGUMENT", 422),
        ConnectorFailureCode.AUTH_REQUIRED: ("AUTH_REQUIRED", 401),
        ConnectorFailureCode.PERMISSION_DENIED: ("PERMISSION_DENIED", 403),
        ConnectorFailureCode.NOT_FOUND: ("NOT_FOUND", 404),
        ConnectorFailureCode.RATE_LIMITED: ("UPSTREAM_UNAVAILABLE", 429),
        ConnectorFailureCode.UPSTREAM_UNAVAILABLE: ("UPSTREAM_UNAVAILABLE", 502),
        ConnectorFailureCode.TIMEOUT: ("UPSTREAM_UNAVAILABLE", 504),
        ConnectorFailureCode.CONNECTION_UNAVAILABLE: ("SERVICE_BUSY", 503),
        ConnectorFailureCode.MALFORMED_RESPONSE: ("UPSTREAM_UNAVAILABLE", 502),
    }
    error_code, status_code = mapping.get(error.code, ("UPSTREAM_UNAVAILABLE", 502))
    raise ApiError(
        error_code=error_code,
        user_message="Google connector request could not be completed.",
        status_code=status_code,
        request_id=request_id,
        retryable=error.retryable,
        detail_code=error.detail_code,
    ) from error
