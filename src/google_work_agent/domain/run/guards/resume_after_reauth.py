"""Guard for restoring the persisted pre-reauth safe Run phase."""
from google_work_agent.domain.enums import RunStatus
from google_work_agent.domain.run.model import RunTransitionRejected

_SAFE = frozenset({
    RunStatus.ANALYZING,
    RunStatus.RETRIEVING,
    RunStatus.PLANNING,
    RunStatus.WAITING_APPROVAL,
    RunStatus.EXECUTING,
    RunStatus.VERIFYING,
    RunStatus.RECOVERY_REQUIRED,
})


def guard_resume_after_reauth(current_status: RunStatus, *, resume_status: RunStatus) -> None:
    if current_status is not RunStatus.REAUTH_REQUIRED:
        raise RunTransitionRejected("resume_after_reauth requires REAUTH_REQUIRED")
    if resume_status not in _SAFE:
        raise RunTransitionRejected("resume_after_reauth requires a persisted safe status")
