"""Canonical reauthentication resume transition."""
from google_work_agent.domain.enums import RunStatus
from google_work_agent.domain.run.guards.resume_after_reauth import guard_resume_after_reauth


def transition_resume_after_reauth(current_status: RunStatus, *, resume_status: RunStatus) -> RunStatus:
    guard_resume_after_reauth(current_status, resume_status=resume_status)
    return resume_status
