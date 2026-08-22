"""Start-Google-OAuth response contract."""

from google_work_agent.api.schemas.model import ApiModel


class GoogleOAuthStartResponse(ApiModel):
    flow_id: str
    authorization_url: str
    callback_url: str
    expires_at_ms: int
    oauth_environment: str
    scopes: list[str]
    api_contract_version: str
