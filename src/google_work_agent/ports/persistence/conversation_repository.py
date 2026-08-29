"""Conversation persistence and bounded list-projection port."""

from dataclasses import dataclass
from typing import Protocol

from google_work_agent.domain.conversation.model import Conversation as ConversationRecord


@dataclass(frozen=True, slots=True)
class ConversationListRecord:
    conversation: ConversationRecord
    latest_message_at_ms: int | None
    open_run_id: str | None


class ConversationRepository(Protocol):
    def create(self, conversation: ConversationRecord) -> None: ...

    def get(self, conversation_id: str) -> ConversationRecord | None: ...

    def list_keyset(
        self,
        *,
        account_id: str,
        cursor: str | None,
        page_size: int,
        search: str | None = None,
    ) -> tuple[tuple[ConversationListRecord, ...], str | None]: ...

    def touch_updated_at(self, conversation_id: str, *, updated_at_ms: int) -> None: ...
