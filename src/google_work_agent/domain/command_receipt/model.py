"""Command-receipt domain model."""

from dataclasses import dataclass
from enum import StrEnum

from google_work_agent.domain.results import ResultCode


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
