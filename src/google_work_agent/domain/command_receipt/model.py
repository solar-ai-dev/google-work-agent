"""Command-receipt domain model."""

from dataclasses import dataclass
from enum import StrEnum

from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.run.model import RunCommand, RunStatusV1


class DuplicateCommandError(Exception):
    """A command id was reused with a conflicting request identity."""


class CommandReceiptStatus(StrEnum):
    RECEIVED = "RECEIVED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class CommandReceipt:
    command_id: str
    command_type: str
    request_hash: str
    aggregate_type: str
    aggregate_id: str | None
    status: CommandReceiptStatus
    result_code: ResultCode | None
    result_version: int | None
    response: object | None
    response_json: str | None
    created_at_ms: int
    completed_at_ms: int | None


@dataclass(frozen=True, slots=True)
class AnswerOnlyResponse:
    applied: bool
    result_code: ResultCode
    current_status: RunStatusV1
    current_version: int
    next_allowed_commands: tuple[RunCommand, ...]
    conflict_detail: str | None = None
    assistant_message_id: str | None = None
