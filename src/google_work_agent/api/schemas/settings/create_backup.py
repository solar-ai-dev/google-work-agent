"""Create-backup wire response."""

from google_work_agent.api.schemas.model import ApiModel


class BackupResponse(ApiModel):
    backup: dict[str, object]
    api_contract_version: str
