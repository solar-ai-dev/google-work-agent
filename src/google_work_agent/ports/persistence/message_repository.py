"""Message persistence port."""
from typing import Protocol
from google_work_agent.ports.models import MessageRecord

class MessageRepository(Protocol):
    def add(self, message: MessageRecord) -> None: ...
    def find_assistant_message(self, *, run_id: str, content: str) -> MessageRecord | None: ...
