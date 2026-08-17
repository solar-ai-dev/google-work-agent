"""Application contracts for uncertain-result and mismatch recovery."""

from dataclasses import dataclass
from enum import StrEnum

from google_work_agent.ports import ResourceSnapshot


@dataclass(frozen=True, slots=True)
class MarkWriteActionUnknownResultCommand:
    command_id: str
    request_hash: str
    action_id: str
    attempt_id: str
    expected_action_version: int
    expected_attempt_version: int
    error_code: str
    error_detail: str


@dataclass(frozen=True, slots=True)
class RecoverExistingWriteResultCommand:
    command_id: str
    request_hash: str
    action_id: str
    attempt_id: str
    expected_action_version: int
    expected_attempt_version: int
    snapshot: ResourceSnapshot
    safe_error_code: str | None = None


@dataclass(frozen=True, slots=True)
class RecoverUnknownCreateActionCommand:
    command_id: str
    request_hash: str
    action_id: str
    attempt_id: str
    expected_action_version: int
    expected_attempt_version: int


@dataclass(frozen=True, slots=True)
class RecoverUnknownUpdateActionCommand:
    command_id: str
    request_hash: str
    action_id: str
    attempt_id: str
    expected_action_version: int
    expected_attempt_version: int


@dataclass(frozen=True, slots=True)
class RecoverUnknownSendActionCommand:
    command_id: str
    request_hash: str
    action_id: str
    attempt_id: str
    expected_action_version: int
    expected_attempt_version: int


@dataclass(frozen=True, slots=True)
class RecoverUnknownDeleteActionCommand:
    command_id: str
    request_hash: str
    action_id: str
    attempt_id: str
    expected_action_version: int
    expected_attempt_version: int


@dataclass(frozen=True, slots=True)
class ResolveUnknownWriteAsFailedCommand:
    command_id: str
    request_hash: str
    action_id: str
    attempt_id: str
    expected_action_version: int
    expected_attempt_version: int
    error_code: str
    error_detail: str


@dataclass(frozen=True, slots=True)
class PrepareWriteRetryCommand:
    command_id: str
    request_hash: str
    action_id: str
    expected_action_version: int


class RecoveryResolutionKind(StrEnum):
    ACCEPT_PARTIAL = "ACCEPT_PARTIAL"
    CREATE_CORRECTIVE_PLAN = "CREATE_CORRECTIVE_PLAN"
    FAIL = "FAIL"


@dataclass(frozen=True, slots=True)
class ResolveMismatchRecoveryCommand:
    command_id: str
    request_hash: str
    run_id: str
    action_id: str
    expected_run_version: int
    resolution_kind: RecoveryResolutionKind
    corrective_plan_id: str | None = None


@dataclass(frozen=True, slots=True)
class RequireWriteReauthCommand:
    command_id: str
    request_hash: str
    run_id: str
    action_id: str | None
    safe_error_code: str
