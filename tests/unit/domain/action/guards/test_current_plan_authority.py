from google_work_agent.domain.action.guards.current_plan_authority import (
    guard_current_plan_authority,
)
from google_work_agent.domain.plan.model import PlanStatusV1


def test_current_plan_authority_rejects_superseded_and_noncurrent_children() -> None:
    assert (
        guard_current_plan_authority(
            plan_status=PlanStatusV1.WAITING_APPROVAL, plan_is_current=True
        )
        is None
    )
    assert (
        guard_current_plan_authority(plan_status=PlanStatusV1.SUPERSEDED, plan_is_current=True)
        is not None
    )
    assert (
        guard_current_plan_authority(
            plan_status=PlanStatusV1.WAITING_APPROVAL, plan_is_current=False
        )
        is not None
    )
