"""Get-Google-connection response contract."""

from google_work_agent.api.schemas.model import ApiModel


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
    safe_error_code: str | None = None
    safe_error_description: str | None = None
    api_contract_version: str
