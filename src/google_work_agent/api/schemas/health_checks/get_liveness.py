"""Get-liveness wire contract."""

from google_work_agent.api.schemas.common import ApiModel


class LiveResponse(ApiModel):
    status: str
    service_instance_id: str
    release_version: str
    api_contract_version: str
    occurred_at_ms: int
