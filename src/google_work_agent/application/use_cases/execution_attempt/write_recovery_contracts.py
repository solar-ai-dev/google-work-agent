"""Execution-attempt-owner contracts for uncertain-result recovery."""

from dataclasses import dataclass

from google_work_agent.ports.connector.contracts.google_workspace import ResourceSnapshot


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
    mcp_request_id: str | None = None


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


@dataclass(frozen=True, slots=True)
class RequireWriteReauthCommand:
    command_id: str
    request_hash: str
    run_id: str
    action_id: str | None
    safe_error_code: str
    mcp_request_id: str | None = None
