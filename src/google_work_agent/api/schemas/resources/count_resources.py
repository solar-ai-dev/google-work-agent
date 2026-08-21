"""Count-resources wire response."""

from google_work_agent.api.schemas.common import ApiModel


class ResourceCountResponse(ApiModel):
    source: str
    total_count: int
    api_contract_version: str
