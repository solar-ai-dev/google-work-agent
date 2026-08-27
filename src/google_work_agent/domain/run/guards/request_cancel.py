"""Guard for requesting Run cancellation."""

from google_work_agent.domain.run.model import (
    TERMINAL_RUN_STATUSES,
    RunStatusV1,
    RunTransitionRejected,
)


def guard_request_cancel(current_status: RunStatusV1) -> None:
    if current_status in TERMINAL_RUN_STATUSES:
        raise RunTransitionRejected(
            f"request_cancel rejects terminal status {current_status.value}"
        )
