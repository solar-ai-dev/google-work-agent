"""Canonical Confirmation resume transition."""

from google_work_agent.domain.run.guards.resume_confirmation import guard_resume_confirmation
from google_work_agent.domain.run.model import RunStatusV1


def transition_resume_confirmation(
    current_status: RunStatusV1, *, resume_status: RunStatusV1
) -> RunStatusV1:
    guard_resume_confirmation(current_status, resume_status=resume_status)
    return resume_status
