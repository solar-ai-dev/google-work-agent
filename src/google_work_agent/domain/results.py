"""Common domain command result."""

from dataclasses import dataclass
from enum import StrEnum


class InvariantViolationError(Exception):
    """A lifecycle invariant cannot be represented as a normal command result."""


class ResultCode(StrEnum):
    """Domain command result codes for pure transition checks."""

    TRANSITION_APPLIED = "TRANSITION_APPLIED"
    STATE_CONFLICT = "STATE_CONFLICT"
    VERSION_CONFLICT = "VERSION_CONFLICT"
    DUPLICATE_COMMAND = "DUPLICATE_COMMAND"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    SCHEMA_VIOLATION = "SCHEMA_VIOLATION"
    NO_PROGRESS = "NO_PROGRESS"
    RESOLUTION_NOT_ALLOWED = "RESOLUTION_NOT_ALLOWED"


@dataclass(frozen=True, slots=True)
class CommandResult[StatusType: StrEnum, CommandType: StrEnum]:
    """Result returned by pure domain transition functions."""

    applied: bool
    result_code: ResultCode
    current_status: StatusType
    current_version: int
    next_allowed_commands: tuple[CommandType, ...]
    conflict_detail: str | None = None
