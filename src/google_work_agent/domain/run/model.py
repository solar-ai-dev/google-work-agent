"""Run lifecycle domain primitives owned by the run semantic package."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RunStatusV1(StrEnum):
    CREATED = "CREATED"
    ANALYZING = "ANALYZING"
    RETRIEVING = "RETRIEVING"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    PLANNING = "PLANNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    REAUTH_REQUIRED = "REAUTH_REQUIRED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class TerminalResultKindV1(StrEnum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class Run:
    id: str
    conversation_id: str
    status: RunStatusV1
    version: int
    started_at_ms: int
    finished_at_ms: int | None
    entry_mode: str = ""
    langgraph_thread_id: str = ""
    requested_mode: str = ""
    actual_runtime: str | None = None
    terminal_result_kind: TerminalResultKindV1 | None = None
    budget_json: str = "{}"


@dataclass(frozen=True, slots=True)
class RunCreate:
    id: str
    conversation_id: str
    entry_mode: str
    status: RunStatusV1
    langgraph_thread_id: str
    requested_mode: str
    actual_runtime: str | None
    budget_json: str
    version: int
    started_at_ms: int
    finished_at_ms: int | None
    terminal_result_kind: TerminalResultKindV1 | None = None


class RunCommand(StrEnum):
    """Run lifecycle transition commands."""

    START_RUN = "START_RUN"
    START_ANALYSIS = "START_ANALYSIS"
    BEGIN_RETRIEVAL = "BEGIN_RETRIEVAL"
    BEGIN_PLANNING = "BEGIN_PLANNING"
    BEGIN_VERIFICATION = "BEGIN_VERIFICATION"
    REQUEST_CONFIRMATION = "REQUEST_CONFIRMATION"
    RESUME_CONFIRMATION = "RESUME_CONFIRMATION"
    BLOCK_RUN = "BLOCK_RUN"
    COMPLETE_ANSWER_ONLY_RUN = "COMPLETE_ANSWER_ONLY_RUN"
    COMPLETE_WRITE_RUN = "COMPLETE_WRITE_RUN"
    REQUEST_CANCEL = "REQUEST_CANCEL"
    FINALIZE_CANCEL = "FINALIZE_CANCEL"
    REQUIRE_REAUTH = "REQUIRE_REAUTH"
    RESUME_AFTER_REAUTH = "RESUME_AFTER_REAUTH"


TERMINAL_RUN_STATUSES = frozenset(
    {
        RunStatusV1.COMPLETED,
        RunStatusV1.CANCELLED,
        RunStatusV1.FAILED,
        RunStatusV1.BLOCKED,
    }
)

PREEMPTING_RUN_STATUSES = TERMINAL_RUN_STATUSES | frozenset(
    {
        RunStatusV1.CANCEL_REQUESTED,
        RunStatusV1.REAUTH_REQUIRED,
        RunStatusV1.RECOVERY_REQUIRED,
    }
)


def is_terminal_run_status(status: RunStatusV1) -> bool:
    return status in TERMINAL_RUN_STATUSES


def is_preempting_run_status(status: RunStatusV1) -> bool:
    return status in PREEMPTING_RUN_STATUSES


def next_allowed_run_commands(current_status: RunStatusV1) -> tuple[RunCommand, ...]:
    """Project exact Run-owner commands without invoking persistence or adapters."""
    allowed: list[RunCommand] = []
    if current_status is RunStatusV1.CREATED:
        allowed.append(RunCommand.START_ANALYSIS)
    if current_status in {RunStatusV1.ANALYZING, RunStatusV1.PLANNING}:
        allowed.append(RunCommand.BEGIN_RETRIEVAL)
    if current_status in {RunStatusV1.ANALYZING, RunStatusV1.RETRIEVING}:
        allowed.append(RunCommand.BEGIN_PLANNING)
    if current_status in {
        RunStatusV1.ANALYZING,
        RunStatusV1.RETRIEVING,
        RunStatusV1.PLANNING,
        RunStatusV1.WAITING_APPROVAL,
        RunStatusV1.VERIFYING,
    }:
        allowed.append(RunCommand.REQUEST_CONFIRMATION)
    if current_status is RunStatusV1.WAITING_CONFIRMATION:
        allowed.append(RunCommand.RESUME_CONFIRMATION)
    if current_status in {
        RunStatusV1.ANALYZING,
        RunStatusV1.RETRIEVING,
        RunStatusV1.PLANNING,
    }:
        allowed.append(RunCommand.COMPLETE_ANSWER_ONLY_RUN)
    if current_status in {
        RunStatusV1.CREATED,
        RunStatusV1.ANALYZING,
        RunStatusV1.RETRIEVING,
        RunStatusV1.WAITING_CONFIRMATION,
        RunStatusV1.PLANNING,
        RunStatusV1.WAITING_APPROVAL,
        RunStatusV1.VERIFYING,
    }:
        allowed.append(RunCommand.BLOCK_RUN)
    if current_status in {RunStatusV1.WAITING_APPROVAL, RunStatusV1.CANCEL_REQUESTED}:
        allowed.append(RunCommand.BEGIN_VERIFICATION)
    if current_status in {RunStatusV1.WAITING_APPROVAL, RunStatusV1.VERIFYING}:
        allowed.append(RunCommand.COMPLETE_WRITE_RUN)
    if current_status in {
        RunStatusV1.CANCEL_REQUESTED,
        RunStatusV1.VERIFYING,
        RunStatusV1.REAUTH_REQUIRED,
    }:
        allowed.append(RunCommand.FINALIZE_CANCEL)
    if current_status in {
        RunStatusV1.ANALYZING,
        RunStatusV1.RETRIEVING,
        RunStatusV1.PLANNING,
        RunStatusV1.WAITING_APPROVAL,
        RunStatusV1.EXECUTING,
        RunStatusV1.VERIFYING,
        RunStatusV1.CANCEL_REQUESTED,
        RunStatusV1.RECOVERY_REQUIRED,
    }:
        allowed.append(RunCommand.REQUIRE_REAUTH)
    if current_status is RunStatusV1.REAUTH_REQUIRED:
        allowed.append(RunCommand.RESUME_AFTER_REAUTH)
    if current_status not in TERMINAL_RUN_STATUSES:
        allowed.append(RunCommand.REQUEST_CANCEL)
    return tuple(allowed)


class RunTransitionRejected(ValueError):
    """Raised when a requested Run lifecycle transition violates the domain contract."""


def require_status(
    current_status: RunStatusV1, allowed: frozenset[RunStatusV1], operation: str
) -> None:
    if current_status not in allowed:
        allowed_text = ", ".join(sorted(status.value for status in allowed))
        raise RunTransitionRejected(
            f"{operation} requires status in {{{allowed_text}}}; got {current_status.value}"
        )
