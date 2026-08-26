"""Execution-attempt domain model and lifecycle vocabulary."""

from dataclasses import dataclass
from enum import StrEnum

from google_work_agent.domain.action.model import ActionCommand, ActionStatus
from google_work_agent.domain.results import ResultCode


class ExecutionAttemptStatus(StrEnum):
    CLAIMED = "CLAIMED"
    EXECUTING = "EXECUTING"
    UNKNOWN_RESULT = "UNKNOWN_RESULT"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class ExecutionAttemptCommand(StrEnum):
    BEGIN_EXECUTION_ATTEMPT = "BEGIN_EXECUTION_ATTEMPT"
    ABORT_CLAIMED_EXECUTION = "ABORT_CLAIMED_EXECUTION"
    STORE_SUCCESS = "STORE_SUCCESS"
    MARK_FAILED = "MARK_FAILED"
    MARK_UNKNOWN_RESULT = "MARK_UNKNOWN_RESULT"
    RECOVER_EXISTING_RESULT = "RECOVER_EXISTING_RESULT"
    RESOLVE_AS_FAILED = "RESOLVE_AS_FAILED"


class AttemptOutcome(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNKNOWN_RESULT = "UNKNOWN_RESULT"


@dataclass(frozen=True, slots=True)
class ExecutionAttempt:
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
class ExecutionAttemptTransitionDecision:
    applied: bool
    result_code: ResultCode
    action_status: ActionStatus
    action_version: int
    attempt_status: ExecutionAttemptStatus
    attempt_version: int
    conflict_detail: str | None = None

    @property
    def current_status(self) -> ActionStatus:
        return self.action_status

    @property
    def current_version(self) -> int:
        return self.action_version

    @property
    def next_allowed_commands(self) -> tuple[ActionCommand, ...]:
        return ()
