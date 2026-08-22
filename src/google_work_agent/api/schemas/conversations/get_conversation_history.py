"""Get-conversation-history wire response."""

from google_work_agent.api.schemas.model import ApiModel


class ConversationHistoryResponse(ApiModel):
    conversation: dict[str, object]
    messages: list[dict[str, object]]
    runs: list[dict[str, object]]
    truncated: bool
    api_contract_version: str
