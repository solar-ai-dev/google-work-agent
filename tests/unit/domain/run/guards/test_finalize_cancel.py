import pytest

from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.approval.model import ApprovalStatusV1
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.run.guards.finalize_cancel import guard_finalize_cancel
from google_work_agent.domain.run.model import RunStatusV1, RunTransitionRejected


def _guard(**changes: object) -> None:
    values = {
        "cancel_intent_active": True,
        "plan_status": PlanStatusV1.WAITING_APPROVAL,
        "plan_is_current": True,
        "action_statuses": (ActionStatusV1.CANCELLED,),
        "approval_statuses": (ApprovalStatusV1.REVOKED,),
        "attempt_statuses": (ExecutionAttemptStatusV1.FAILED,),
    }
    values.update(changes)
    guard_finalize_cancel(RunStatusV1.CANCEL_REQUESTED, **values)  # type: ignore[arg-type]


def test_finalize_cancel__requires_settled_children__and_durable_intent() -> None:
    _guard()
    for change in (
        {"cancel_intent_active": False},
        {"action_statuses": (ActionStatusV1.EXECUTING,)},
        {"approval_statuses": (ApprovalStatusV1.ACTIVE,)},
        {"attempt_statuses": (ExecutionAttemptStatusV1.EXECUTING,)},
    ):
        with pytest.raises(RunTransitionRejected):
            _guard(**change)
