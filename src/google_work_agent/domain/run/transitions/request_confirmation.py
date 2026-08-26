"""Canonical Run transition for request confirmation."""
from google_work_agent.domain.enums import RunStatus
from google_work_agent.domain.run.guards.request_confirmation import guard_request_confirmation


def transition_request_confirmation(
    current_status: RunStatus,
    *,
    durable_review_disposition: str | None = None,
    unresolved_external_effect_count: int = 0,
) -> RunStatus:
    """Return the next Run status after enforcing the canonical guard."""
    guard_request_confirmation(
        current_status,
        durable_review_disposition=durable_review_disposition,
        unresolved_external_effect_count=unresolved_external_effect_count,
    )
    return RunStatus.WAITING_CONFIRMATION
