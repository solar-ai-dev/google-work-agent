from google_work_agent.domain.action.guards.current_plan_authority import (
    guard_current_plan_authority,
)
from google_work_agent.domain.plan.model import PlanStatusV1


def test_current_plan__authority_rejects_superseded__and_noncurrent_children() -> None:
    assert (
        guard_current_plan_authority(
            plan_status=PlanStatusV1.WAITING_APPROVAL,
            plan_is_current=True,
            allowed_statuses=frozenset({PlanStatusV1.WAITING_APPROVAL}),
        )
        is None
    )
    assert (
        guard_current_plan_authority(
            plan_status=PlanStatusV1.SUPERSEDED,
            plan_is_current=True,
            allowed_statuses=frozenset({PlanStatusV1.WAITING_APPROVAL}),
        )
        is not None
    )
    assert (
        guard_current_plan_authority(
            plan_status=PlanStatusV1.WAITING_APPROVAL,
            plan_is_current=False,
            allowed_statuses=frozenset({PlanStatusV1.WAITING_APPROVAL}),
        )
        is not None
    )


def test_current_plan__authority_rejects_current__but_disallowed_status() -> None:
    assert (
        guard_current_plan_authority(
            plan_status=PlanStatusV1.DRAFT,
            plan_is_current=True,
            allowed_statuses=frozenset({PlanStatusV1.WAITING_APPROVAL}),
        )
        == "Plan status must be WAITING_APPROVAL for this child mutation"
    )
