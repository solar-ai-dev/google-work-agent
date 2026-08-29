"""Canonical Conversation history wire projection."""

from typing import Literal

from google_work_agent.api.schemas.conversations.list_conversations import ConversationItemV1
from google_work_agent.api.schemas.model import ApiModel


class ConversationMessageV1(ApiModel):
    schema_version: Literal[1] = 1
    id: str
    run_id: str | None
    role: str
    content: str
    created_at_ms: int


class ConversationHistoryRunV1(ApiModel):
    schema_version: Literal[1] = 1
    run_id: str
    status: str
    started_at_ms: int
    finished_at_ms: int | None


class ConversationHistoryResponseV1(ApiModel):
    schema_version: Literal[1] = 1
    conversation: ConversationItemV1
    messages: list[ConversationMessageV1]
    runs: list[ConversationHistoryRunV1]
    truncated: bool
    api_contract_version: str


__all__ = [
    "ConversationHistoryResponseV1",
    "ConversationHistoryRunV1",
    "ConversationMessageV1",
]
