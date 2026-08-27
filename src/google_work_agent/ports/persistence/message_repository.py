"""Message persistence port."""

from typing import Protocol

from google_work_agent.domain.message.model import Message as MessageRecord


class MessageRepository(Protocol):
    def append_user_message(self, message: MessageRecord) -> None: ...

    def append_terminal_assistant_message(self, message: MessageRecord) -> None: ...

    def list_by_conversation_keyset(
        self,
        *,
        conversation_id: str,
        cursor: str | None,
        page_size: int,
    ) -> tuple[tuple[MessageRecord, ...], str | None]: ...
