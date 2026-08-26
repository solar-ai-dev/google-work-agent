import pytest

from google_work_agent.domain.action.model import ActionStatus
from google_work_agent.domain.run.model import RunStatus, RunTransitionRejected
from google_work_agent.domain.run.transitions.begin_planning import transition_begin_planning


@pytest.mark.parametrize("status", (RunStatus.ANALYZING, RunStatus.RETRIEVING))
def test_begin_planning_applies_pre_publish_transition(status: RunStatus) -> None:
    assert transition_begin_planning(status) is RunStatus.PLANNING


@pytest.mark.parametrize("disposition", ("REVISE", "RETRIEVE_MORE", "ROUTE_RECONSIDERATION"))
@pytest.mark.parametrize("status", (RunStatus.WAITING_APPROVAL, RunStatus.VERIFYING))
def test_begin_planning_applies_guarded_published_review_reentry(
    status: RunStatus, disposition: str
) -> None:
    assert (
        transition_begin_planning(
            status,
            durable_review_disposition=disposition,
            has_current_plan=True,
            current_action_statuses=(ActionStatus.PROPOSED,),
        )
        is RunStatus.PLANNING
    )


@pytest.mark.parametrize("disposition", (None, "PASS", "CONFIRM", "BLOCK"))
def test_begin_planning_rejects_unapproved_published_review_disposition(
    disposition: str | None,
) -> None:
    with pytest.raises(RunTransitionRejected):
        transition_begin_planning(
            RunStatus.WAITING_APPROVAL,
            durable_review_disposition=disposition,
            has_current_plan=True,
            current_action_statuses=(ActionStatus.PROPOSED,),
        )


@pytest.mark.parametrize(
    "status",
    (
        ActionStatus.EXECUTING,
        ActionStatus.UNKNOWN_RESULT,
        ActionStatus.EXECUTED,
        ActionStatus.MISMATCH,
    ),
)
def test_begin_planning_rejects_unresolved_external_effect(status: ActionStatus) -> None:
    with pytest.raises(RunTransitionRejected):
        transition_begin_planning(
            RunStatus.VERIFYING,
            durable_review_disposition="REVISE",
            has_current_plan=True,
            current_action_statuses=(status,),
            unresolved_external_effect_count=1,
        )


def test_begin_planning_context_adjustment_requires_child_authority_fence() -> None:
    with pytest.raises(RunTransitionRejected):
        transition_begin_planning(
            RunStatus.WAITING_APPROVAL,
            user_context_adjustment=True,
            has_current_plan=True,
            current_action_statuses=(ActionStatus.PROPOSED,),
            active_approval_count=1,
        )


def test_begin_planning_applies_context_adjustment_when_fence_is_clear() -> None:
    assert (
        transition_begin_planning(
            RunStatus.WAITING_APPROVAL,
            user_context_adjustment=True,
            has_current_plan=True,
            current_action_statuses=(ActionStatus.PROPOSED, ActionStatus.MODIFIED),
        )
        is RunStatus.PLANNING
    )


def test_begin_planning_rejects_unrelated_status() -> None:
    with pytest.raises(RunTransitionRejected):
        transition_begin_planning(RunStatus.FAILED)
