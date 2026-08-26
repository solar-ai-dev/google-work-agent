"""Canonical guard for entering a confirmation interrupt."""

from google_work_agent.domain.enums import RunStatus
from google_work_agent.domain.run.model import RunTransitionRejected, require_status

_PRE_PUBLISH = frozenset({RunStatus.ANALYZING, RunStatus.RETRIEVING, RunStatus.PLANNING})
_PUBLISHED_REVIEW = frozenset({RunStatus.WAITING_APPROVAL, RunStatus.VERIFYING})


def guard_request_confirmation(
    current_status: RunStatus,
    *,
    durable_review_disposition: str | None = None,
    unresolved_external_effect_count: int = 0,
) -> None:
    """Require the exact pre-publish or published Review confirmation source."""
    require_status(
        current_status,
        _PRE_PUBLISH | _PUBLISHED_REVIEW,
        "request_confirmation",
    )
    if current_status in _PUBLISHED_REVIEW:
        if durable_review_disposition != "CONFIRM":
            raise RunTransitionRejected(
                "published request_confirmation requires durable Review CONFIRM"
            )
        if unresolved_external_effect_count:
            raise RunTransitionRejected(
                "published request_confirmation requires no unresolved external effect"
            )
