"""List-resources wire response."""

from google_work_agent.api.schemas.common import ApiModel


class ResourceListResponse(ApiModel):
    source: str
    items: list[dict[str, object]]
    next_page_token: str | None
    api_contract_version: str
