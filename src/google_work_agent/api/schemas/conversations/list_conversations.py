"""Canonical list-conversations wire projection."""

from typing import Literal

from google_work_agent.api.schemas.model import ApiModel


class ConversationItemV1(ApiModel):
    schema_version: Literal[1] = 1
    conversation_id: str
    title: str | None
    latest_message_at_ms: int | None
    open_run_id: str | None


class ConversationListResponseV1(ApiModel):
    schema_version: Literal[1] = 1
    items: list[ConversationItemV1]
    next_cursor: str | None


__all__ = [
    "ConversationItemV1",
    "ConversationListResponseV1",
]
