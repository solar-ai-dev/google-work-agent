"""Domain and policy core package."""

from google_work_agent.domain.action_risk import (
    MAX_ACTION_RISK_JSON_BYTES,
    canonicalize_action_risk,
    normalize_action_risk,
    parse_action_risk_json,
)
from google_work_agent.domain.canonical import (
    calculate_canonical_json_hash,
    canonicalize_json_value,
)
from google_work_agent.domain.commands import ActionCommand, RunCommand
from google_work_agent.domain.enums import (
    ActionStatus,
    ApprovalRequirement,
    ApprovalStatus,
    EffectType,
    ExecutionAttemptStatus,
    RecoveryPolicy,
    ResultCode,
    RunStatus,
    VerificationPolicy,
    VerificationStatus,
)
from google_work_agent.domain.errors import (
    CommandHashMismatchError,
    DomainError,
    DuplicateCommandError,
    InvalidTransitionError,
    InvariantViolationError,
    PolicyViolationError,
    VersionConflictError,
)
from google_work_agent.domain.policy import (
    ApprovalIntegrityInput,
    EvidencePolicyInput,
    validate_approval_integrity,
    validate_evidence_policy,
)
from google_work_agent.domain.results import CommandResult
from google_work_agent.domain.task_duplicate import (
    DuplicateDecision,
    DuplicateFreshness,
    TaskDuplicateCandidate,
    TaskDuplicateResult,
    evaluate_task_duplicate,
    normalize_scheduled_date,
    normalize_task_title,
)
from google_work_agent.domain.tool_registry import (
    DEFAULT_POLICY_VERSION,
    DEFAULT_TOOL_SCHEMA_VERSION,
    SignedToolRegistry,
    ToolRegistryEntry,
    build_p0_tool_registry,
)
from google_work_agent.domain.transitions import (
    next_allowed_action_commands,
    next_allowed_run_commands,
    transition_action,
    transition_run,
)

__all__ = [
    "ActionCommand",
    "ActionStatus",
    "ApprovalIntegrityInput",
    "ApprovalRequirement",
    "ApprovalStatus",
    "CommandHashMismatchError",
    "CommandResult",
    "DEFAULT_POLICY_VERSION",
    "DEFAULT_TOOL_SCHEMA_VERSION",
    "DomainError",
    "DuplicateDecision",
    "DuplicateFreshness",
    "DuplicateCommandError",
    "EvidencePolicyInput",
    "EffectType",
    "ExecutionAttemptStatus",
    "InvalidTransitionError",
    "InvariantViolationError",
    "MAX_ACTION_RISK_JSON_BYTES",
    "PolicyViolationError",
    "RecoveryPolicy",
    "ResultCode",
    "RunCommand",
    "RunStatus",
    "SignedToolRegistry",
    "ToolRegistryEntry",
    "TaskDuplicateCandidate",
    "TaskDuplicateResult",
    "VerificationPolicy",
    "VerificationStatus",
    "VersionConflictError",
    "build_p0_tool_registry",
    "calculate_canonical_json_hash",
    "canonicalize_action_risk",
    "canonicalize_json_value",
    "evaluate_task_duplicate",
    "next_allowed_action_commands",
    "next_allowed_run_commands",
    "normalize_scheduled_date",
    "normalize_task_title",
    "normalize_action_risk",
    "parse_action_risk_json",
    "transition_action",
    "transition_run",
    "validate_approval_integrity",
    "validate_evidence_policy",
]
