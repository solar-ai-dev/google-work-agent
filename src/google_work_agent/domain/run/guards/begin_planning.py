"""Canonical guards for entering the Planning lifecycle phase."""

from __future__ import annotations

from collections.abc import Collection

from google_work_agent.domain.action.model import ActionStatus
from google_work_agent.domain.run.model import RunStatus, RunTransitionRejected, require_status

_PRE_PUBLISH = frozenset({RunStatus.ANALYZING, RunStatus.RETRIEVING})
_PUBLISHED_REVIEW = frozenset({RunStatus.WAITING_APPROVAL, RunStatus.VERIFYING})
_REVIEW_REENTRY_DISPOSITIONS = frozenset({"REVISE", "RETRIEVE_MORE", "ROUTE_RECONSIDERATION"})
_CONTEXT_ADJUSTABLE_ACTIONS = frozenset({ActionStatus.PROPOSED, ActionStatus.MODIFIED})


def guard_begin_planning(
    current_status: RunStatus,
    *,
    durable_review_disposition: str | None = None,
    user_context_adjustment: bool = False,
    has_current_plan: bool = False,
    current_action_statuses: Collection[ActionStatus] = (),
    active_approval_count: int = 0,
    unresolved_external_effect_count: int = 0,
    expected_revisions_match: bool = True,
) -> None:
    """Enforce pre-publish and guarded published-Plan re-entry branches."""
    if user_context_adjustment:
        require_status(
            current_status,
            frozenset({RunStatus.WAITING_APPROVAL}),
            "begin_planning.user_context_adjustment",
        )
        if not has_current_plan:
            raise RunTransitionRejected("user context adjustment requires a current Plan")
        if not current_action_statuses or any(
            status not in _CONTEXT_ADJUSTABLE_ACTIONS for status in current_action_statuses
        ):
            raise RunTransitionRejected(
                "user context adjustment requires only PROPOSED/MODIFIED Actions"
            )
        if active_approval_count or unresolved_external_effect_count:
            raise RunTransitionRejected(
                "user context adjustment requires zero child execution authority"
            )
        if not expected_revisions_match:
            raise RunTransitionRejected("user context adjustment revision mismatch")
        return

    if durable_review_disposition is not None:
        require_status(current_status, _PUBLISHED_REVIEW, "begin_planning.published_review")
        if not has_current_plan:
            raise RunTransitionRejected("published review re-entry requires a current Plan")
        if durable_review_disposition not in _REVIEW_REENTRY_DISPOSITIONS:
            raise RunTransitionRejected(
                "durable Review disposition does not permit planning re-entry"
            )
        if unresolved_external_effect_count:
            raise RunTransitionRejected(
                "published review re-entry requires resolved external effects"
            )
        return

    require_status(current_status, _PRE_PUBLISH, "begin_planning")
