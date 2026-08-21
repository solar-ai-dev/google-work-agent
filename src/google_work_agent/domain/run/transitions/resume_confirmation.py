"""Canonical Confirmation resume transition."""
from google_work_agent.domain.enums import RunStatus
from google_work_agent.domain.run.guards.resume_confirmation import guard_resume_confirmation

def transition_resume_confirmation(current_status: RunStatus, *, resume_status: RunStatus) -> RunStatus:
    guard_resume_confirmation(current_status, resume_status=resume_status)
    return resume_status
