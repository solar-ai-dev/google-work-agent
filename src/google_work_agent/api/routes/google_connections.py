"""Google connector connection routes over canonical Application use cases."""

from fastapi import APIRouter, Header, Request

from google_work_agent.api.dependencies.access_control import enforce_access
from google_work_agent.api.dependencies.contract_version import (
    enforce_supported_api_contract_version,
)
from google_work_agent.api.dependencies.google_connections import GoogleRouteDependency
from google_work_agent.api.errors.api_request_error import ApiRequestError
from google_work_agent.api.schemas.google_connections.disconnect_google import (
    GoogleDisconnectResponse,
)
from google_work_agent.api.schemas.google_connections.get_google_connection import (
    GoogleConnectionResponse,
)
from google_work_agent.api.schemas.google_connections.start_google_oauth import (
    GoogleOAuthStartResponse,
)
from google_work_agent.application.use_cases.connection.get_connection_status import (
    GetConnectionStatusHandler,
    GetConnectionStatusQuery,
)
from google_work_agent.application.use_cases.connection.revoke_connection import (
    RevokeConnectionCommand,
    RevokeConnectionHandler,
)
from google_work_agent.application.use_cases.connection.start_authorization import (
    StartAuthorizationCommand,
    StartAuthorizationHandler,
)
from google_work_agent.ports.connector.connector_failure import (
    ConnectorFailureCode,
    ConnectorOperationFailure,
)
from google_work_agent.ports.connector.oauth_credential_port import OAuthEnvironment
from google_work_agent.ports.system.api_access_port import EndpointPolicy

router = APIRouter(prefix="/api/v1/connections/google")


@router.post("/start", response_model=GoogleOAuthStartResponse)
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
    handler = dependencies.start_authorization_handler()
    if not isinstance(handler, StartAuthorizationHandler):
        raise ApiRequestError(
            error_code="SERVICE_BUSY",
            user_message="Google OAuth provider is not configured.",
            status_code=503,
            request_id=request.state.request_id,
            detail_code="GOOGLE_OAUTH_UNAVAILABLE",
        )
    try:
        started = handler(
            StartAuthorizationCommand(
                command_id=request.state.request_id,
                connector_id="google_workspace",
                environment=OAuthEnvironment.DEVELOPMENT,
                requested_scopes=("openid",),
            )
        ).authorization
    except ConnectorOperationFailure as error:
        _raise_google_failure(error, request_id=request.state.request_id)
    return GoogleOAuthStartResponse(
        flow_id=started.callback_id,
        authorization_url=started.authorization_url,
        callback_url="",
        expires_at_ms=0,
        oauth_environment=OAuthEnvironment.DEVELOPMENT.value,
        scopes=["openid"],
        api_contract_version=dependencies.api_contract_version,
    )


@router.get("/status", response_model=GoogleConnectionResponse)
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
    handler = dependencies.get_connection_status_handler()
    if not isinstance(handler, GetConnectionStatusHandler):
        raise ApiRequestError(
            error_code="SERVICE_BUSY",
            user_message="Google connection provider is not configured.",
            status_code=503,
            request_id=request.state.request_id,
            detail_code="GOOGLE_CONNECTION_UNAVAILABLE",
        )
    try:
        result = handler(GetConnectionStatusQuery(connector_id="google_workspace")).connection
    except ConnectorOperationFailure as error:
        _raise_google_failure(error, request_id=request.state.request_id)
    return GoogleConnectionResponse(
        connected=result.connection_status == "CONNECTED",
        credential_state=result.connection_status,
        account_email=result.display_email,
        display_name=None,
        granted_scopes=list(result.granted_scopes),
        missing_scopes=list(result.missing_required_scopes),
        reauth_required=result.connection_status == "REAUTH_REQUIRED",
        oauth_environment=OAuthEnvironment.DEVELOPMENT.value,
        last_checked_at_ms=0,
        safe_error_code=None,
        safe_error_description=None,
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
    status_handler = dependencies.get_connection_status_handler()
    handler = dependencies.revoke_connection_handler()
    if not isinstance(status_handler, GetConnectionStatusHandler) or not isinstance(
        handler, RevokeConnectionHandler
    ):
        raise ApiRequestError(
            error_code="SERVICE_BUSY",
            user_message="Google disconnect provider is not configured.",
            status_code=503,
            request_id=request.state.request_id,
            detail_code="GOOGLE_DISCONNECT_UNAVAILABLE",
        )
    try:
        current = status_handler(
            GetConnectionStatusQuery(connector_id="google_workspace")
        ).connection
        result = handler(
            RevokeConnectionCommand(
                command_id=request.state.request_id,
                connector_id="google_workspace",
                account_id=current.account_id or "current",
            )
        ).revocation
    except ConnectorOperationFailure as error:
        _raise_google_failure(error, request_id=request.state.request_id)
    return GoogleDisconnectResponse(
        disconnected=result.connection_status == "DISCONNECTED",
        credential_deleted=result.local_credential_deleted,
        revoke_attempted=result.revocation_attempted,
        revoke_succeeded=(
            result.revocation_attempted and result.connection_status == "DISCONNECTED"
        ),
        credential_state=result.connection_status,
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
        raise ApiRequestError(
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
    raise ApiRequestError(
        error_code=error_code,
        user_message="Google connector request could not be completed.",
        status_code=status_code,
        request_id=request_id,
        retryable=error.retryable,
        detail_code=error.detail_code,
    ) from error
