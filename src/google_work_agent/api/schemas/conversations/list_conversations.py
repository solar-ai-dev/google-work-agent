"""List-conversations wire response."""

from google_work_agent.api.schemas.model import ApiModel


class ConversationListResponse(ApiModel):
    items: list[dict[str, object]]
    next_cursor: str | None
    api_contract_version: str
