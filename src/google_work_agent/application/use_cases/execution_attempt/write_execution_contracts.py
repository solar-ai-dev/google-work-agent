"""Execution-attempt-owner contracts for claimed write execution."""

from __future__ import annotations

from dataclasses import dataclass

from google_work_agent.ports.connector.contracts.google_workspace import ResourceSnapshot


@dataclass(frozen=True, slots=True)
class ClaimWriteActionCommand:
    command_id: str
    request_hash: str
    action_id: str
    expected_version: int
    source_snapshot: dict[str, object]
    attempt_id: str
    nonce: str


@dataclass(frozen=True, slots=True)
class CompletedWriteAction:
    resource_ref_id: str
    response_metadata_json: str
    snapshot_projection_json: str


@dataclass(frozen=True, slots=True)
class StoreWriteActionSuccessCommand:
    command_id: str
    request_hash: str
    action_id: str
    attempt_id: str
    expected_action_version: int
    expected_attempt_version: int
    snapshot: ResourceSnapshot


@dataclass(frozen=True, slots=True)
class MarkWriteActionFailedCommand:
    command_id: str
    request_hash: str
    action_id: str
    attempt_id: str
    expected_action_version: int
    expected_attempt_version: int
    error_code: str
    error_detail: str


@dataclass(frozen=True, slots=True)
class VerifyWriteActionCommand:
    command_id: str
    request_hash: str
    action_id: str
    attempt_id: str
    expected_action_version: int
    verification_id: str


@dataclass(frozen=True, slots=True)
class WriteActionResponse:
    applied: bool
    result_code: str
    action_id: str
    action_status: str
    action_version: int
    next_allowed_commands: tuple[str, ...]
    approval_id: str | None = None
    attempt_id: str | None = None
    claim_token: str | None = None
    safe_error_code: str | None = None
    conflict_detail: str | None = None


@dataclass(frozen=True, slots=True)
class WriteRunResponse:
    applied: bool
    result_code: str
    run_id: str
    run_status: str
    run_version: int
    plan_id: str | None
    plan_status: str | None
    result_kind: str | None = None
    conflict_detail: str | None = None


@dataclass(frozen=True, slots=True)
class ExecutedWriteActionResult:
    snapshot: ResourceSnapshot
    response_metadata_json: str
