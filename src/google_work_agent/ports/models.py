"""Cross-layer persistence and application records."""

from dataclasses import dataclass
from enum import StrEnum

from google_work_agent.domain import (
    ApprovalStatus,
    ExecutionAttemptStatus,
    ResultCode,
    RunCommand,
    RunStatus,
    VerificationStatus,
)


class CommandReceiptStatus(StrEnum):
    """Persisted command receipt lifecycle."""

    RECEIVED = "RECEIVED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"


class PlanStatus(StrEnum):
    """Persisted plan lifecycle values."""

    DRAFT = "DRAFT"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class ResourceSource(StrEnum):
    """Persisted resource source values."""

    GMAIL = "GMAIL"
    TASKS = "TASKS"
    CALENDAR = "CALENDAR"


class StoredResourceType(StrEnum):
    """Persisted resource reference type values."""

    THREAD = "THREAD"
    MESSAGE = "MESSAGE"
    TASK = "TASK"
    EVENT = "EVENT"
    TASK_LIST = "TASK_LIST"
    CALENDAR = "CALENDAR"


class EvidenceOriginType(StrEnum):
    """Persisted evidence origin values."""

    GOOGLE_RESOURCE = "GOOGLE_RESOURCE"
    USER_MESSAGE = "USER_MESSAGE"
    DERIVED = "DERIVED"


class AttemptOutcome(StrEnum):
    """Persisted write execution outcome markers."""

    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNKNOWN_RESULT = "UNKNOWN_RESULT"


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
    response_json: str | None
    created_at_ms: int
    completed_at_ms: int | None


@dataclass(frozen=True, slots=True)
class PlanRecord:
    """Persisted plan projection."""

    id: str
    run_id: str
    revision_no: int
    status: PlanStatus
    summary_text: str | None
    created_at_ms: int


@dataclass(frozen=True, slots=True)
class ActionRecord:
    """Persisted action projection."""

    id: str
    plan_id: str
    position: int
    tool_name: str
    effect_type: str
    approval_requirement: str
    verification_policy: str
    recovery_policy: str
    target_resource_ref_id: str | None
    status: str
    arguments_json: str
    arguments_hash: str
    expected_json: str
    version: int
    created_at_ms: int
    updated_at_ms: int


@dataclass(frozen=True, slots=True)
class ResourceRefRecord:
    """Persisted resource reference projection."""

    id: str
    run_id: str
    source: ResourceSource
    resource_type: StoredResourceType
    resource_id: str
    parent_resource_id: str | None
    canonical_url: str | None
    title: str | None
    event_time_ms: int | None
    version_token: str | None
    metadata_json: str
    captured_at_ms: int


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    """Persisted evidence projection."""

    id: str
    run_id: str
    origin_type: EvidenceOriginType
    resource_ref_id: str | None
    message_id: str | None
    kind: str
    excerpt: str
    locator_json: str | None
    created_at_ms: int


@dataclass(frozen=True, slots=True)
class ApprovalRecord:
    """Persisted approval projection."""

    id: str
    action_id: str
    approval_no: int
    action_version: int
    status: ApprovalStatus
    approved_by_account_id: str
    approved_by_display: str | None
    arguments_snapshot_json: str
    canonical_arguments_hash: str
    source_snapshot_json: str
    source_snapshot_hash: str
    policy_version: str
    tool_schema_version: str
    idempotency_key: str
    recovery_fingerprint: str
    approved_at_ms: int
    expires_at_ms: int
    consumed_at_ms: int | None


@dataclass(frozen=True, slots=True)
class ExecutionAttemptRecord:
    """Persisted write execution attempt projection."""

    id: str
    approval_id: str
    attempt_no: int
    status: ExecutionAttemptStatus
    version: int
    result_resource_ref_id: str | None
    response_metadata_json: str | None
    error_code: str | None
    error_detail_json: str | None
    started_at_ms: int
    finished_at_ms: int | None


@dataclass(frozen=True, slots=True)
class VerificationRecord:
    """Persisted verification projection."""

    id: str
    execution_attempt_id: str
    verification_no: int
    status: VerificationStatus
    normalizer_version: str
    expected_json: str
    actual_json: str | None
    diff_json: str
    verified_at_ms: int


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


@dataclass(frozen=True, slots=True)
class PersistedTraceEventRecord:
    """Trace event row returned by cursor-based queries."""

    id: int
    run_id: str
    action_id: str | None
    event_type: str
    status: str | None
    duration_ms: int | None
    payload_json: str
    created_at_ms: int


@dataclass(frozen=True, slots=True)
class PersistedAuditEventRecord:
    """Audit event row returned by cursor-based queries."""

    id: int
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
