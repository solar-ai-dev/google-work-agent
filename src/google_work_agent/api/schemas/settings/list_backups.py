"""List-backups wire response."""

from google_work_agent.api.schemas.model import ApiModel


class BackupListResponse(ApiModel):
    items: list[dict[str, object]]
    api_contract_version: str
