"""Cross-layer persistence and application records."""

from dataclasses import dataclass
from enum import StrEnum

from google_work_agent.domain import ResultCode, RunCommand, RunStatus


class CommandReceiptStatus(StrEnum):
    """Persisted command receipt lifecycle."""

    RECEIVED = "RECEIVED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class ConversationRecord:
    """Conversation projection used by application services."""

    id: str
    account_id: str
    title: str
    created_at_ms: int
    updated_at_ms: int


@dataclass(frozen=True, slots=True)
class RunRecord:
    """Run projection used by application services."""

    id: str
    conversation_id: str
    status: RunStatus
    version: int
    started_at_ms: int
    finished_at_ms: int | None


@dataclass(frozen=True, slots=True)
class MessageRecord:
    """Persisted message projection."""

    id: str
    conversation_id: str
    run_id: str | None
    role: str
    content: str
    created_at_ms: int


@dataclass(frozen=True, slots=True)
class AnswerOnlyResponse:
    """Stored response snapshot for the answer-only completion command."""

    applied: bool
    result_code: ResultCode
    current_status: RunStatus
    current_version: int
    next_allowed_commands: tuple[RunCommand, ...]
    conflict_detail: str | None = None
    assistant_message_id: str | None = None


@dataclass(frozen=True, slots=True)
class CommandReceiptRecord:
    """Persisted command receipt snapshot."""

    command_id: str
    command_type: str
    request_hash: str
    aggregate_type: str
    aggregate_id: str | None
    status: CommandReceiptStatus
    result_code: ResultCode | None
    result_version: int | None
    response: AnswerOnlyResponse | None
    created_at_ms: int
    completed_at_ms: int | None


@dataclass(frozen=True, slots=True)
class AuditEventRecord:
    """Audit event payload accepted by persistence adapters."""

    account_id: str | None
    run_id: str | None
    action_id: str | None
    actor_type: str
    actor_id: str
    actor_display: str | None
    event_type: str
    outcome: str
    metadata_json: str
    created_at_ms: int


@dataclass(frozen=True, slots=True)
class TraceEventRecord:
    """Trace event payload accepted by persistence adapters."""

    run_id: str
    action_id: str | None
    event_type: str
    status: str | None
    duration_ms: int | None
    payload_json: str
    created_at_ms: int
