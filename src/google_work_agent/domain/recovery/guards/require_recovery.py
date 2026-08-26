"""Guard for entering the Recovery lifecycle."""

from google_work_agent.domain.run.model import (
    TERMINAL_RUN_STATUSES,
    RunStatus,
    RunTransitionRejected,
)


def guard_require_recovery(current_status: RunStatus) -> None:
    """Recovery may only suspend a non-terminal Run."""
    if current_status in TERMINAL_RUN_STATUSES:
        raise RunTransitionRejected(
            f"require_recovery rejects terminal status {current_status.value}"
        )
