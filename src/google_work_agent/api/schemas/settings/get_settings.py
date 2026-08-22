"""Get-settings wire response."""

from google_work_agent.api.schemas.model import ApiModel


class SettingsResponse(ApiModel):
    settings: dict[str, object]
    api_contract_version: str
