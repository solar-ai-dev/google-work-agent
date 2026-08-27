import pytest

from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.run.model import RunStatusV1, RunTransitionRejected
from google_work_agent.domain.run.transitions.begin_planning import transition_begin_planning


@pytest.mark.parametrize("status", (RunStatusV1.ANALYZING, RunStatusV1.RETRIEVING))
def test_begin_planning_applies_pre_publish_transition(status: RunStatusV1) -> None:
    assert transition_begin_planning(status) is RunStatusV1.PLANNING


@pytest.mark.parametrize("disposition", ("REVISE", "RETRIEVE_MORE", "ROUTE_RECONSIDERATION"))
@pytest.mark.parametrize("status", (RunStatusV1.WAITING_APPROVAL, RunStatusV1.VERIFYING))
def test_begin_planning_applies_guarded_published_review_reentry(
    status: RunStatusV1, disposition: str
) -> None:
    assert (
        transition_begin_planning(
            status,
            durable_review_disposition=disposition,
            has_current_plan=True,
            current_action_statuses=(ActionStatusV1.PROPOSED,),
        )
        is RunStatusV1.PLANNING
    )


@pytest.mark.parametrize("disposition", (None, "PASS", "CONFIRM", "BLOCK"))
def test_begin_planning_rejects_unapproved_published_review_disposition(
    disposition: str | None,
) -> None:
    with pytest.raises(RunTransitionRejected):
        transition_begin_planning(
            RunStatusV1.WAITING_APPROVAL,
            durable_review_disposition=disposition,
            has_current_plan=True,
            current_action_statuses=(ActionStatusV1.PROPOSED,),
        )


@pytest.mark.parametrize(
    "status",
    (
        ActionStatusV1.EXECUTING,
        ActionStatusV1.UNKNOWN_RESULT,
        ActionStatusV1.EXECUTED,
        ActionStatusV1.MISMATCH,
    ),
)
def test_begin_planning_rejects_unresolved_external_effect(status: ActionStatusV1) -> None:
    with pytest.raises(RunTransitionRejected):
        transition_begin_planning(
            RunStatusV1.VERIFYING,
            durable_review_disposition="REVISE",
            has_current_plan=True,
            current_action_statuses=(status,),
            unresolved_external_effect_count=1,
        )


def test_begin_planning_context_adjustment_requires_child_authority_fence() -> None:
    with pytest.raises(RunTransitionRejected):
        transition_begin_planning(
            RunStatusV1.WAITING_APPROVAL,
            user_context_adjustment=True,
            has_current_plan=True,
            current_action_statuses=(ActionStatusV1.PROPOSED,),
            active_approval_count=1,
        )


def test_begin_planning_applies_context_adjustment_when_fence_is_clear() -> None:
    assert (
        transition_begin_planning(
            RunStatusV1.WAITING_APPROVAL,
            user_context_adjustment=True,
            has_current_plan=True,
            current_action_statuses=(ActionStatusV1.PROPOSED, ActionStatusV1.MODIFIED),
        )
        is RunStatusV1.PLANNING
    )


def test_begin_planning_rejects_unrelated_status() -> None:
    with pytest.raises(RunTransitionRejected):
        transition_begin_planning(RunStatusV1.FAILED)
