"""Conversation persistence port."""

from typing import Protocol

from google_work_agent.ports.models import ConversationRecord


class ConversationRepository(Protocol):
    def create(self, conversation: ConversationRecord) -> None: ...

    def get(self, conversation_id: str) -> ConversationRecord | None: ...

    def list_keyset(
        self,
        *,
        account_id: str,
        cursor: str | None,
        page_size: int,
    ) -> tuple[tuple[ConversationRecord, ...], str | None]: ...

    def touch_updated_at(self, conversation_id: str, *, updated_at_ms: int) -> None: ...
