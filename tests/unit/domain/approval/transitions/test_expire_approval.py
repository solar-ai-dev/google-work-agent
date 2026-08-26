from google_work_agent.domain.action.model import ActionStatus
from google_work_agent.domain.approval.model import ApprovalStatus
from google_work_agent.domain.approval.transitions.expire_approval import transition_expire_approval
from google_work_agent.domain.plan.model import PlanStatus


def test_expire_approval_is_a_coupled_mutation() -> None:
    assert transition_expire_approval(
        action_status=ActionStatus.APPROVED,
        approval_status=ApprovalStatus.ACTIVE,
        plan_status=PlanStatus.WAITING_APPROVAL,
        plan_is_current=True,
    ) == (ActionStatus.EXPIRED, ApprovalStatus.EXPIRED)
