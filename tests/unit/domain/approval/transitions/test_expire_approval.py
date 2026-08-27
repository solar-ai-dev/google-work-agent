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
