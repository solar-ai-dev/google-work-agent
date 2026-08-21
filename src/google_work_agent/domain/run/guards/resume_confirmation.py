"""Guard for restoring the pre-confirmation safe Run phase."""
from google_work_agent.domain.enums import RunStatus
from google_work_agent.domain.run.model import RunTransitionRejected
_SAFE = frozenset({RunStatus.ANALYZING, RunStatus.RETRIEVING, RunStatus.PLANNING})

def guard_resume_confirmation(current_status: RunStatus, *, resume_status: RunStatus) -> None:
    if current_status is not RunStatus.WAITING_CONFIRMATION:
        raise RunTransitionRejected("resume_confirmation requires WAITING_CONFIRMATION")
    if resume_status not in _SAFE:
        raise RunTransitionRejected("resume_confirmation requires a registered pre-confirmation safe status")
