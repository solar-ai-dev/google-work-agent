"""Get-current-Google-account response contract."""

from google_work_agent.api.schemas.model import ApiModel


class GoogleAccountProjection(ApiModel):
    account_id: str | None
    email: str | None
    display_name: str | None


class CurrentGoogleAccountResponse(ApiModel):
    account: GoogleAccountProjection | None
    api_contract_version: str


__all__ = ["CurrentGoogleAccountResponse", "GoogleAccountProjection"]
