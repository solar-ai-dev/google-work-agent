"""Domain enum values fixed by the SQLite schema and transition contract."""

from enum import StrEnum


class RunStatus(StrEnum):
    """Run status values from the `runs.status` SQL constraint."""

    CREATED = "CREATED"
    ANALYZING = "ANALYZING"
    RETRIEVING = "RETRIEVING"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    PLANNING = "PLANNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    REAUTH_REQUIRED = "REAUTH_REQUIRED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class ActionStatus(StrEnum):
    """Action status values from the `actions.status` SQL constraint."""

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


class ApprovalStatus(StrEnum):
    """Approval lifecycle status values."""

    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CONSUMED = "CONSUMED"
    REVOKED = "REVOKED"


class ApprovalRequirement(StrEnum):
    """Approval requirement values fixed by the action policy contract."""

    NONE = "NONE"
    REQUIRED = "REQUIRED"


class ExecutionAttemptStatus(StrEnum):
    """Execution attempt lifecycle status values."""

    CLAIMED = "CLAIMED"
    EXECUTING = "EXECUTING"
    UNKNOWN_RESULT = "UNKNOWN_RESULT"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class VerificationStatus(StrEnum):
    """Verification result status values."""

    VERIFIED = "VERIFIED"
    MISMATCH = "MISMATCH"
    NOT_FOUND = "NOT_FOUND"
    ERROR = "ERROR"


class VerificationPolicy(StrEnum):
    """Verification policy values fixed by the action policy contract."""

    NONE = "NONE"
    GET_COMPARE = "GET_COMPARE"
    SENT_LOOKUP = "SENT_LOOKUP"
    GET_ABSENT = "GET_ABSENT"


class RecoveryPolicy(StrEnum):
    """Recovery policy values fixed by the action policy contract."""

    NONE = "NONE"
    GET_TARGET = "GET_TARGET"
    RESOURCE_SEARCH = "RESOURCE_SEARCH"
    MESSAGE_SEARCH = "MESSAGE_SEARCH"


class RecoveryResolution(StrEnum):
    """Registered Run recovery variants from the canonical transition contract."""

    RECHECK = "RECHECK"
    ACCEPT_PARTIAL = "ACCEPT_PARTIAL"
    CREATE_CORRECTIVE_PLAN = "CREATE_CORRECTIVE_PLAN"
    CANCEL = "CANCEL"
    FAIL = "FAIL"


class EffectType(StrEnum):
    """Supported P0 action effect types."""

    READ = "READ"
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    SEND = "SEND"
    DELETE = "DELETE"


class ResultCode(StrEnum):
    """Domain command result codes for pure transition checks."""

    TRANSITION_APPLIED = "TRANSITION_APPLIED"
    STATE_CONFLICT = "STATE_CONFLICT"
    VERSION_CONFLICT = "VERSION_CONFLICT"
    DUPLICATE_COMMAND = "DUPLICATE_COMMAND"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    SCHEMA_VIOLATION = "SCHEMA_VIOLATION"
