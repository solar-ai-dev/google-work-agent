"""Run lifecycle domain primitives owned by the run semantic package."""

from __future__ import annotations

from enum import StrEnum

from google_work_agent.domain.enums import RunStatus


class RunCommand(StrEnum):
    """Run lifecycle transition commands."""

    START_ANALYSIS = "START_ANALYSIS"
    BEGIN_RETRIEVAL = "BEGIN_RETRIEVAL"
    BEGIN_PLANNING = "BEGIN_PLANNING"
    BEGIN_VERIFICATION = "BEGIN_VERIFICATION"
    REQUEST_CONFIRMATION = "REQUEST_CONFIRMATION"
    RESUME_CONFIRMATION = "RESUME_CONFIRMATION"
    BLOCK_RUN = "BLOCK_RUN"
    FAIL_RUN = "FAIL_RUN"
    PUBLISH_PLAN = "PUBLISH_PLAN"
    COMPLETE_ANSWER_ONLY_RUN = "COMPLETE_ANSWER_ONLY_RUN"
    COMPLETE_WRITE_RUN = "COMPLETE_WRITE_RUN"
    FINALIZE_ACTION_OUTCOMES = "FINALIZE_ACTION_OUTCOMES"
    REQUEST_CANCEL = "REQUEST_CANCEL"
    FINALIZE_CANCEL = "FINALIZE_CANCEL"
    REQUIRE_REAUTH = "REQUIRE_REAUTH"
    REQUIRE_RECOVERY = "REQUIRE_RECOVERY"
    RESOLVE_RECOVERY = "RESOLVE_RECOVERY"


TERMINAL_RUN_STATUSES = frozenset(
    {
        RunStatus.COMPLETED,
        RunStatus.CANCELLED,
        RunStatus.FAILED,
        RunStatus.BLOCKED,
    }
)


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
