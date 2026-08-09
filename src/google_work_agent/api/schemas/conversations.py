"""Conversation API schemas."""

from .common import ApiModel, ContractVersionedRequest


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


class ConversationListResponse(ApiModel):
    items: list[dict[str, object]]
    next_cursor: str | None
    api_contract_version: str


class LatestConversationRunResponse(ApiModel):
    run: dict[str, object] | None
    api_contract_version: str
