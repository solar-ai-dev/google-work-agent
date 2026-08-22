"""Get-run wire response."""

from google_work_agent.api.schemas.model import ApiModel


class RunSnapshotResponse(ApiModel):
    snapshot: dict[str, object]
    api_contract_version: str
