"""Common domain command result."""

from dataclasses import dataclass
from enum import StrEnum

from google_work_agent.domain.enums import ResultCode


@dataclass(frozen=True, slots=True)
class CommandResult[StatusType: StrEnum, CommandType: StrEnum]:
    """Result returned by pure domain transition functions."""

    applied: bool
    result_code: ResultCode
    current_status: StatusType
    current_version: int
    next_allowed_commands: tuple[CommandType, ...]
    conflict_detail: str | None = None
