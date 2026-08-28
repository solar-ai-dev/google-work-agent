import pytest

from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.approval.model import ApprovalStatusV1
from google_work_agent.domain.approval.transitions.expire_approval import transition_expire_approval
from google_work_agent.domain.plan.model import PlanStatusV1


def test_expire_approval_is_a_coupled_mutation() -> None:
    assert transition_expire_approval(
        action_status=ActionStatusV1.APPROVED,
        approval_status=ApprovalStatusV1.ACTIVE,
        plan_status=PlanStatusV1.WAITING_APPROVAL,
        plan_is_current=True,
    ) == (ActionStatusV1.EXPIRED, ApprovalStatusV1.EXPIRED)


@pytest.mark.parametrize(
    "plan_status",
    [status for status in PlanStatusV1 if status is not PlanStatusV1.WAITING_APPROVAL],
)
def test_expire_approval_rejects_non_waiting_plan(plan_status: PlanStatusV1) -> None:
    with pytest.raises(ValueError):
        transition_expire_approval(
            action_status=ActionStatusV1.APPROVED,
            approval_status=ApprovalStatusV1.ACTIVE,
            plan_status=plan_status,
            plan_is_current=True,
        )
