"""Repository and transaction port definitions."""

from contextlib import AbstractContextManager
from typing import Protocol

from google_work_agent.domain import CommandResult, RunCommand, RunStatus
from google_work_agent.ports.models import (
    AnswerOnlyResponse,
    AuditEventRecord,
    CommandReceiptRecord,
    ConversationRecord,
    MessageRecord,
    RunRecord,
)


class ConversationRepository(Protocol):
    """Conversation access required by product-core application services."""

    def get_by_id(self, conversation_id: str) -> ConversationRecord | None:
        """Return a conversation by identifier."""


class RunRepository(Protocol):
    """Run access and state transition persistence."""

    def get_by_id(self, run_id: str) -> RunRecord | None:
        """Return a run by identifier."""

    def complete_answer_only_run(
        self,
        run_id: str,
        *,
        expected_version: int,
        finished_at_ms: int,
    ) -> CommandResult[RunStatus, RunCommand]:
        """Complete a run through the answer-only transition path."""


class MessageRepository(Protocol):
    """Message persistence required by the answer-only flow."""

    def add(self, message: MessageRecord) -> None:
        """Persist a new message row."""

    def find_assistant_message(
        self,
        *,
        run_id: str,
        content: str,
    ) -> MessageRecord | None:
        """Return a matching assistant message if one already exists."""


class CommandReceiptRepository(Protocol):
    """Command receipt persistence for durable idempotency."""

    def get_by_command_id(self, command_id: str) -> CommandReceiptRecord | None:
        """Return an existing command receipt."""

    def add_received(
        self,
        *,
        command_id: str,
        command_type: str,
        request_hash: str,
        aggregate_type: str,
        aggregate_id: str | None,
        created_at_ms: int,
    ) -> None:
        """Insert a new RECEIVED receipt inside the active transaction."""

    def finish(
        self,
        *,
        command_id: str,
        response: AnswerOnlyResponse,
        completed_at_ms: int,
    ) -> None:
        """Finalize a receipt as APPLIED or REJECTED with a stored response."""


class AuditRepository(Protocol):
    """Append-only audit persistence."""

    def add(self, event: AuditEventRecord) -> None:
        """Append an audit event row."""


class UnitOfWork(AbstractContextManager["UnitOfWork"], Protocol):
    """Transactional repository bundle."""

    conversations: ConversationRepository
    runs: RunRepository
    messages: MessageRepository
    command_receipts: CommandReceiptRepository
    audits: AuditRepository

    def commit(self) -> None:
        """Commit the current transaction."""

    def rollback(self) -> None:
        """Rollback the current transaction."""
