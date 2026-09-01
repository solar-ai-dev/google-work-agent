"""Execution-attempt-owner contracts for claimed write execution."""

from __future__ import annotations

from dataclasses import dataclass

from google_work_agent.ports.connector.contracts.google_workspace import ResourceSnapshot


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
    verification_id: str | None = None
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
