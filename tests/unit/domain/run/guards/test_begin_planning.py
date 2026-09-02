import pytest

from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.run.guards.begin_planning import guard_begin_planning
from google_work_agent.domain.run.model import RunStatusV1, RunTransitionRejected


def test_begin_planning_covers__pre_publish_review__and_user_adjustment_branches() -> None:
    guard_begin_planning(RunStatusV1.ANALYZING)
    guard_begin_planning(
        RunStatusV1.VERIFYING,
        durable_review_disposition="REVISE",
        has_current_plan=True,
    )
    guard_begin_planning(
        RunStatusV1.WAITING_APPROVAL,
        user_context_adjustment=True,
        has_current_plan=True,
        current_action_statuses=(ActionStatusV1.PROPOSED,),
    )
    with pytest.raises(RunTransitionRejected):
        guard_begin_planning(
            RunStatusV1.WAITING_APPROVAL,
            user_context_adjustment=True,
            has_current_plan=True,
            current_action_statuses=(ActionStatusV1.EXECUTING,),
        )
