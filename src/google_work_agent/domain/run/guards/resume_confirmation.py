"""Guard for restoring the pre-confirmation safe Run phase."""

from google_work_agent.domain.run.model import RunStatusV1, RunTransitionRejected

_SAFE = frozenset(
    {
        RunStatusV1.ANALYZING,
        RunStatusV1.RETRIEVING,
        RunStatusV1.PLANNING,
        RunStatusV1.WAITING_APPROVAL,
        RunStatusV1.VERIFYING,
    }
)


def guard_resume_confirmation(current_status: RunStatusV1, *, resume_status: RunStatusV1) -> None:
    if current_status is not RunStatusV1.WAITING_CONFIRMATION:
        raise RunTransitionRejected("resume_confirmation requires WAITING_CONFIRMATION")
    if resume_status not in _SAFE:
        raise RunTransitionRejected(
            "resume_confirmation requires a registered pre-confirmation safe status"
        )
