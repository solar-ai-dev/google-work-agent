"""Canonical Run transition for begin planning."""

from __future__ import annotations

from collections.abc import Collection

from google_work_agent.domain.enums import ActionStatus, RunStatus
from google_work_agent.domain.run.guards.begin_planning import guard_begin_planning


def transition_begin_planning(
    current_status: RunStatus,
    *,
    durable_review_disposition: str | None = None,
    user_context_adjustment: bool = False,
    has_current_plan: bool = False,
    current_action_statuses: Collection[ActionStatus] = (),
    active_approval_count: int = 0,
    unresolved_external_effect_count: int = 0,
    expected_revisions_match: bool = True,
) -> RunStatus:
    """Return the next Run status after enforcing the canonical guard."""
    guard_begin_planning(
        current_status,
        durable_review_disposition=durable_review_disposition,
        user_context_adjustment=user_context_adjustment,
        has_current_plan=has_current_plan,
        current_action_statuses=current_action_statuses,
        active_approval_count=active_approval_count,
        unresolved_external_effect_count=unresolved_external_effect_count,
        expected_revisions_match=expected_revisions_match,
    )
    return RunStatus.PLANNING
