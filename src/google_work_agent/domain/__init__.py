"""Domain and policy core package."""

from google_work_agent.domain.commands import ActionCommand, RunCommand
from google_work_agent.domain.enums import (
    ActionStatus,
    ApprovalStatus,
    EffectType,
    ExecutionAttemptStatus,
    ResultCode,
    RunStatus,
    VerificationStatus,
)
from google_work_agent.domain.errors import (
    CommandHashMismatchError,
    DomainError,
    DuplicateCommandError,
    InvalidTransitionError,
    InvariantViolationError,
    VersionConflictError,
)
from google_work_agent.domain.results import CommandResult
from google_work_agent.domain.transitions import (
    next_allowed_action_commands,
    next_allowed_run_commands,
    transition_action,
    transition_run,
)

__all__ = [
    "ActionCommand",
    "ActionStatus",
    "ApprovalStatus",
    "CommandHashMismatchError",
    "CommandResult",
    "DomainError",
    "DuplicateCommandError",
    "EffectType",
    "ExecutionAttemptStatus",
    "InvalidTransitionError",
    "InvariantViolationError",
    "ResultCode",
    "RunCommand",
    "RunStatus",
    "VerificationStatus",
    "VersionConflictError",
    "next_allowed_action_commands",
    "next_allowed_run_commands",
    "transition_action",
    "transition_run",
]
