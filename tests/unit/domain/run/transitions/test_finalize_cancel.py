import pytest

from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.approval.model import ApprovalStatusV1
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.run.model import RunStatusV1, RunTransitionRejected
from google_work_agent.domain.run.transitions.finalize_cancel import transition_finalize_cancel


def test_finalize_cancel_applies_canonical_transition():
    assert (
        transition_finalize_cancel(
            RunStatusV1.CANCEL_REQUESTED,
            cancel_intent_active=True,
            plan_status=PlanStatusV1.CANCELLED,
            plan_is_current=True,
            action_statuses=(ActionStatusV1.CANCELLED,),
            approval_statuses=(ApprovalStatusV1.REVOKED,),
            attempt_statuses=(),
        )
        is RunStatusV1.CANCELLED
    )


def test_finalize_cancel_rejects_active_approval():
    with pytest.raises(RunTransitionRejected):
        transition_finalize_cancel(
            RunStatusV1.CANCEL_REQUESTED,
            cancel_intent_active=True,
            plan_status=PlanStatusV1.ACTIVE,
            plan_is_current=True,
            action_statuses=(ActionStatusV1.CANCELLED,),
            approval_statuses=(ApprovalStatusV1.ACTIVE,),
            attempt_statuses=(ExecutionAttemptStatusV1.FAILED,),
        )


def test_finalize_cancel_allows_pre_plan_cancellation():
    assert (
        transition_finalize_cancel(
            RunStatusV1.CANCEL_REQUESTED,
            cancel_intent_active=True,
            plan_status=None,
            plan_is_current=True,
            action_statuses=(),
            approval_statuses=(),
            attempt_statuses=(),
        )
        is RunStatusV1.CANCELLED
    )
