"""Create-conversation wire contracts."""

from google_work_agent.api.schemas.common import ApiModel, ContractVersionedRequest


class CreateConversationRequest(ContractVersionedRequest):
    command_id: str
    conversation_id: str
    account_id: str
    title: str


class ConversationResponse(ApiModel):
    applied: bool
    result_code: str
    conversation_id: str
    account_id: str
    title: str
    updated_at_ms: int
    conflict_detail: str | None = None
