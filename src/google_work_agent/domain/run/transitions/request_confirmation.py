"""Canonical Run transition for request confirmation."""

from google_work_agent.domain.run.guards.request_confirmation import guard_request_confirmation
from google_work_agent.domain.run.model import RunStatusV1


def transition_request_confirmation(
    current_status: RunStatusV1,
    *,
    durable_review_disposition: str | None = None,
    unresolved_external_effect_count: int = 0,
) -> RunStatusV1:
    """Return the next Run status after enforcing the canonical guard."""
    guard_request_confirmation(
        current_status,
        durable_review_disposition=durable_review_disposition,
        unresolved_external_effect_count=unresolved_external_effect_count,
    )
    return RunStatusV1.WAITING_CONFIRMATION
