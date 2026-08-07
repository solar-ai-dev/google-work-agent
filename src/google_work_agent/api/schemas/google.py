"""Google connection API schemas."""

from google_work_agent.api.schemas.common import ApiModel


class GoogleOAuthStartResponse(ApiModel):
    flow_id: str
    authorization_url: str
    callback_url: str
    expires_at_ms: int
    oauth_environment: str
    scopes: list[str]
    api_contract_version: str


class GoogleConnectionResponse(ApiModel):
    connected: bool
    credential_state: str
    account_email: str | None
    display_name: str | None
    granted_scopes: list[str]
    missing_scopes: list[str]
    reauth_required: bool
    oauth_environment: str
    last_checked_at_ms: int
    api_contract_version: str


class GoogleDisconnectResponse(ApiModel):
    disconnected: bool
    credential_deleted: bool
    revoke_attempted: bool
    revoke_succeeded: bool
    credential_state: str
    api_contract_version: str
