"""Get-latest-conversation-run wire response."""

from google_work_agent.api.schemas.common import ApiModel


class LatestConversationRunResponse(ApiModel):
    run: dict[str, object] | None
    api_contract_version: str
