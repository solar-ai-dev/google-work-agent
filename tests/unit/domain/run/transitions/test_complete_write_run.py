import pytest

from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.run.model import RunStatusV1, RunTransitionRejected
from google_work_agent.domain.run.transitions.complete_write_run import (
    transition_complete_write_run,
)


def test_complete_write_run_applies_canonical_transition():
    assert (
        transition_complete_write_run(
            RunStatusV1.VERIFYING,
            plan_status=PlanStatusV1.ACTIVE,
            plan_is_current=True,
            action_statuses=(ActionStatusV1.VERIFIED,),
            attempt_statuses=(ExecutionAttemptStatusV1.SUCCEEDED,),
            unresolved_required_fact_count=0,
            external_write_count=1,
            cancel_intent_active=False,
        )
        is RunStatusV1.COMPLETED
    )
    assert (
        transition_complete_write_run(
            RunStatusV1.WAITING_APPROVAL,
            plan_status=PlanStatusV1.WAITING_APPROVAL,
            plan_is_current=True,
            action_statuses=(ActionStatusV1.REJECTED,),
            attempt_statuses=(),
            unresolved_required_fact_count=0,
            external_write_count=0,
            cancel_intent_active=False,
        )
        is RunStatusV1.COMPLETED
    )


def test_complete_write_run_rejects_unresolved_attempt():
    with pytest.raises(RunTransitionRejected):
        transition_complete_write_run(
            RunStatusV1.VERIFYING,
            plan_status=PlanStatusV1.ACTIVE,
            plan_is_current=True,
            action_statuses=(ActionStatusV1.VERIFIED,),
            attempt_statuses=(ExecutionAttemptStatusV1.UNKNOWN_RESULT,),
            unresolved_required_fact_count=0,
            external_write_count=1,
            cancel_intent_active=False,
        )
