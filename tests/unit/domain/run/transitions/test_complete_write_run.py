import pytest

from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.run.model import RunStatusV1, RunTransitionRejected
from google_work_agent.domain.run.transitions.complete_write_run import (
    classify_complete_write_run_result,
    transition_complete_write_run,
)


def test_complete_write_run_applies_canonical_transition():
    assert (
        transition_complete_write_run(
            RunStatusV1.VERIFYING,
            plan_status=PlanStatusV1.WAITING_APPROVAL,
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
            plan_status=PlanStatusV1.WAITING_APPROVAL,
            plan_is_current=True,
            action_statuses=(ActionStatusV1.VERIFIED,),
            attempt_statuses=(ExecutionAttemptStatusV1.UNKNOWN_RESULT,),
            unresolved_required_fact_count=0,
            external_write_count=1,
            cancel_intent_active=False,
        )


def test_complete_write_run_rejects_legacy_active_plan_and_failed_action():
    for plan_status, action_statuses in (
        (PlanStatusV1.ACTIVE, (ActionStatusV1.VERIFIED,)),
        (PlanStatusV1.WAITING_APPROVAL, (ActionStatusV1.FAILED,)),
    ):
        with pytest.raises(RunTransitionRejected):
            transition_complete_write_run(
                RunStatusV1.VERIFYING,
                plan_status=plan_status,
                plan_is_current=True,
                action_statuses=action_statuses,
                attempt_statuses=(ExecutionAttemptStatusV1.SUCCEEDED,),
                unresolved_required_fact_count=0,
                external_write_count=1,
                cancel_intent_active=False,
            )


def test_complete_write_run_result_classifier_is_closed_and_exact():
    assert classify_complete_write_run_result((ActionStatusV1.VERIFIED,)).value == "SUCCESS"
    for status in (
        ActionStatusV1.REJECTED,
        ActionStatusV1.CANCELLED,
        ActionStatusV1.BLOCKED,
        ActionStatusV1.DEPENDENCY_BLOCKED,
    ):
        assert classify_complete_write_run_result((ActionStatusV1.VERIFIED, status)).value == (
            "PARTIAL"
        )
    classified = {
        ActionStatusV1.VERIFIED,
        ActionStatusV1.REJECTED,
        ActionStatusV1.CANCELLED,
        ActionStatusV1.BLOCKED,
        ActionStatusV1.DEPENDENCY_BLOCKED,
    }
    for status in set(ActionStatusV1) - classified:
        with pytest.raises(RunTransitionRejected):
            classify_complete_write_run_result((status,))
