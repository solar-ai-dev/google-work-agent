"""Action lifecycle domain model and vocabulary."""

from dataclasses import dataclass
from enum import StrEnum


class PolicyViolationError(Exception):
    """A deterministic Action policy rejected the requested operation."""


class ActionStatus(StrEnum):
    PROPOSED = "PROPOSED"
    MODIFIED = "MODIFIED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    EXECUTING = "EXECUTING"
    UNKNOWN_RESULT = "UNKNOWN_RESULT"
    EXECUTED = "EXECUTED"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    DEPENDENCY_BLOCKED = "DEPENDENCY_BLOCKED"
    MISMATCH = "MISMATCH"
    CANCELLED = "CANCELLED"


class EffectType(StrEnum):
    READ = "READ"
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    SEND = "SEND"
    DELETE = "DELETE"


class ApprovalRequirement(StrEnum):
    NONE = "NONE"
    REQUIRED = "REQUIRED"


class VerificationPolicy(StrEnum):
    NONE = "NONE"
    GET_COMPARE = "GET_COMPARE"
    SENT_LOOKUP = "SENT_LOOKUP"
    GET_ABSENT = "GET_ABSENT"


class RecoveryPolicy(StrEnum):
    NONE = "NONE"
    GET_TARGET = "GET_TARGET"
    RESOURCE_SEARCH = "RESOURCE_SEARCH"
    MESSAGE_SEARCH = "MESSAGE_SEARCH"


@dataclass(frozen=True, slots=True)
class Action:
    id: str
    plan_id: str
    connector_id: str
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
    risk: dict[str, object]
    version: int
    created_at_ms: int
    updated_at_ms: int


@dataclass(frozen=True, slots=True)
class ActionDependency:
    action_id: str
    depends_on_action_id: str


@dataclass(frozen=True, slots=True)
class ActionEvidence:
    action_id: str
    evidence_id: str


class ActionCommand(StrEnum):
    """Action lifecycle transition commands."""

    APPROVE_ACTION = "APPROVE_ACTION"
    MODIFY_ACTION = "MODIFY_ACTION"
    REJECT_ACTION = "REJECT_ACTION"
    REFRESH_EXPIRED_ACTION = "REFRESH_EXPIRED_ACTION"
    CLAIM_READ_ACTION = "CLAIM_READ_ACTION"
    COMPLETE_READ_ACTION = "COMPLETE_READ_ACTION"
    FINALIZE_READ_ACTION = "FINALIZE_READ_ACTION"
    FAIL_READ_ACTION = "FAIL_READ_ACTION"
    PREPARE_WRITE_RETRY = "PREPARE_WRITE_RETRY"
    CANCEL_PENDING_ACTION = "CANCEL_PENDING_ACTION"


def next_allowed_action_commands(
    current_status: ActionStatus, *, effect_type: EffectType
) -> tuple[ActionCommand, ...]:
    """Project only commands owned by the Action aggregate."""
    if effect_type is EffectType.READ:
        by_status = {
            ActionStatus.PROPOSED: (
                ActionCommand.MODIFY_ACTION,
                ActionCommand.REJECT_ACTION,
                ActionCommand.CLAIM_READ_ACTION,
            ),
            ActionStatus.EXECUTING: (
                ActionCommand.COMPLETE_READ_ACTION,
                ActionCommand.FAIL_READ_ACTION,
            ),
            ActionStatus.EXECUTED: (ActionCommand.FINALIZE_READ_ACTION,),
            ActionStatus.FAILED: (ActionCommand.MODIFY_ACTION,),
        }
    else:
        by_status = {
            ActionStatus.PROPOSED: (
                ActionCommand.APPROVE_ACTION,
                ActionCommand.MODIFY_ACTION,
                ActionCommand.REJECT_ACTION,
            ),
            ActionStatus.MODIFIED: (
                ActionCommand.APPROVE_ACTION,
                ActionCommand.MODIFY_ACTION,
                ActionCommand.REJECT_ACTION,
            ),
            ActionStatus.APPROVED: (
                ActionCommand.MODIFY_ACTION,
                ActionCommand.REJECT_ACTION,
                ActionCommand.CANCEL_PENDING_ACTION,
            ),
            ActionStatus.EXPIRED: (
                ActionCommand.REFRESH_EXPIRED_ACTION,
                ActionCommand.MODIFY_ACTION,
                ActionCommand.CANCEL_PENDING_ACTION,
            ),
            ActionStatus.FAILED: (
                ActionCommand.PREPARE_WRITE_RETRY,
                ActionCommand.MODIFY_ACTION,
            ),
        }
    return by_status.get(current_status, ())
