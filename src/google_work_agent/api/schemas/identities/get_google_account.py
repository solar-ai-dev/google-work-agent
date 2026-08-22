"""Get-current-Google-account response contract."""

from google_work_agent.api.schemas.model import ApiModel


class CurrentGoogleAccountResponse(ApiModel):
    account: dict[str, object] | None
    api_contract_version: str
