"""Run lifecycle domain primitives owned by the run semantic package."""
from __future__ import annotations
from google_work_agent.domain.enums import RunStatus

TERMINAL_RUN_STATUSES = frozenset({
    RunStatus.COMPLETED, RunStatus.CANCELLED, RunStatus.FAILED, RunStatus.BLOCKED,
})

class RunTransitionRejected(ValueError):
    """Raised when a requested Run lifecycle transition violates the domain contract."""

def require_status(current_status: RunStatus, allowed: frozenset[RunStatus], operation: str) -> None:
    if current_status not in allowed:
        allowed_text = ", ".join(sorted(status.value for status in allowed))
        raise RunTransitionRejected(
            f"{operation} requires status in {{{allowed_text}}}; got {current_status.value}"
        )
