"""Run lifecycle domain primitives owned by the run semantic package."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RunStatus(StrEnum):
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


@dataclass(frozen=True, slots=True)
class Run:
    id: str
    conversation_id: str
    status: RunStatus
    version: int
    started_at_ms: int
    finished_at_ms: int | None
    entry_mode: str = ""
    langgraph_thread_id: str = ""
    requested_mode: str = ""
    actual_runtime: str | None = None


@dataclass(frozen=True, slots=True)
class RunCreate:
    id: str
    conversation_id: str
    entry_mode: str
    status: RunStatus
    langgraph_thread_id: str
    requested_mode: str
    actual_runtime: str | None
    budget_json: str
    version: int
    started_at_ms: int
    finished_at_ms: int | None


class RunCommand(StrEnum):
    """Run lifecycle transition commands."""

    START_ANALYSIS = "START_ANALYSIS"
    BEGIN_RETRIEVAL = "BEGIN_RETRIEVAL"
    BEGIN_PLANNING = "BEGIN_PLANNING"
    BEGIN_VERIFICATION = "BEGIN_VERIFICATION"
    REQUEST_CONFIRMATION = "REQUEST_CONFIRMATION"
    RESUME_CONFIRMATION = "RESUME_CONFIRMATION"
    BLOCK_RUN = "BLOCK_RUN"
    COMPLETE_ANSWER_ONLY_RUN = "COMPLETE_ANSWER_ONLY_RUN"
    COMPLETE_READ_ONLY_RUN = "COMPLETE_READ_ONLY_RUN"
    COMPLETE_WRITE_RUN = "COMPLETE_WRITE_RUN"
    REQUEST_CANCEL = "REQUEST_CANCEL"
    FINALIZE_CANCEL = "FINALIZE_CANCEL"
    REQUIRE_REAUTH = "REQUIRE_REAUTH"


TERMINAL_RUN_STATUSES = frozenset(
    {
        RunStatus.COMPLETED,
        RunStatus.CANCELLED,
        RunStatus.FAILED,
        RunStatus.BLOCKED,
    }
)

PREEMPTING_RUN_STATUSES = TERMINAL_RUN_STATUSES | frozenset(
    {
        RunStatus.CANCEL_REQUESTED,
        RunStatus.REAUTH_REQUIRED,
        RunStatus.RECOVERY_REQUIRED,
    }
)


def is_terminal_run_status(status: RunStatus) -> bool:
    return status in TERMINAL_RUN_STATUSES


def is_preempting_run_status(status: RunStatus) -> bool:
    return status in PREEMPTING_RUN_STATUSES


def next_allowed_run_commands(current_status: RunStatus) -> tuple[RunCommand, ...]:
    """Project exact Run-owner commands without invoking persistence or adapters."""
    allowed: list[RunCommand] = []
    if current_status is RunStatus.CREATED:
        allowed.append(RunCommand.START_ANALYSIS)
    if current_status in {RunStatus.ANALYZING, RunStatus.PLANNING}:
        allowed.append(RunCommand.BEGIN_RETRIEVAL)
    if current_status in {RunStatus.ANALYZING, RunStatus.RETRIEVING}:
        allowed.append(RunCommand.BEGIN_PLANNING)
    if current_status not in TERMINAL_RUN_STATUSES:
        allowed.append(RunCommand.REQUEST_CANCEL)
    return tuple(allowed)


class RunTransitionRejected(ValueError):
    """Raised when a requested Run lifecycle transition violates the domain contract."""


def require_status(
    current_status: RunStatus, allowed: frozenset[RunStatus], operation: str
) -> None:
    if current_status not in allowed:
        allowed_text = ", ".join(sorted(status.value for status in allowed))
        raise RunTransitionRejected(
            f"{operation} requires status in {{{allowed_text}}}; got {current_status.value}"
        )
