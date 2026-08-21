"""Guard for requiring Run recovery."""
from google_work_agent.domain.enums import RunStatus
from google_work_agent.domain.run.model import TERMINAL_RUN_STATUSES, RunTransitionRejected

def guard_require_recovery(current_status: RunStatus) -> None:
    if current_status in TERMINAL_RUN_STATUSES:
        raise RunTransitionRejected(f"require_recovery rejects terminal status {current_status.value}")
