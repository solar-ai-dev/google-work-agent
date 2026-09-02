import pytest

from google_work_agent.domain.action.model import ActionStatusV1, EffectType
from google_work_agent.domain.action.transitions.approve_action import transition_approve_action
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.run.model import RunStatusV1


def test_approve_action__requires_write__and_passed_review() -> None:
    rejected = transition_approve_action(
        ActionStatusV1.MODIFIED,
        1,
        1,
        effect_type=EffectType.CREATE,
        plan_review_passed=False,
        plan_status=PlanStatusV1.WAITING_APPROVAL,
        plan_is_current=True,
        run_status=RunStatusV1.WAITING_APPROVAL,
    )
    approved = transition_approve_action(
        ActionStatusV1.MODIFIED,
        1,
        1,
        effect_type=EffectType.CREATE,
        plan_review_passed=True,
        plan_status=PlanStatusV1.WAITING_APPROVAL,
        plan_is_current=True,
        run_status=RunStatusV1.WAITING_APPROVAL,
    )
    read = transition_approve_action(
        ActionStatusV1.PROPOSED,
        0,
        0,
        effect_type=EffectType.READ,
        plan_review_passed=True,
        plan_status=PlanStatusV1.WAITING_APPROVAL,
        plan_is_current=True,
        run_status=RunStatusV1.WAITING_APPROVAL,
    )
    assert not rejected.applied
    assert approved.applied and approved.current_status is ActionStatusV1.APPROVED
    assert not read.applied


def test_approve_action__rejects_superseded__plan_child() -> None:
    result = transition_approve_action(
        ActionStatusV1.PROPOSED,
        1,
        1,
        effect_type=EffectType.CREATE,
        plan_review_passed=True,
        plan_status=PlanStatusV1.SUPERSEDED,
        plan_is_current=False,
        run_status=RunStatusV1.WAITING_APPROVAL,
    )
    assert not result.applied
    assert result.conflict_detail == "superseded or noncurrent Plan children are history-only"


@pytest.mark.parametrize("run_status", list(RunStatusV1))
def test_approve_action__exact_parent__run_status_matrix(run_status: RunStatusV1) -> None:
    result = transition_approve_action(
        ActionStatusV1.PROPOSED,
        0,
        0,
        effect_type=EffectType.CREATE,
        plan_review_passed=True,
        plan_status=PlanStatusV1.WAITING_APPROVAL,
        plan_is_current=True,
        run_status=run_status,
    )

    assert result.applied is (run_status in {RunStatusV1.WAITING_APPROVAL, RunStatusV1.VERIFYING})


@pytest.mark.parametrize(
    "plan_status",
    [status for status in PlanStatusV1 if status is not PlanStatusV1.WAITING_APPROVAL],
)
def test_approve_action__rejects_every__other_plan_status(plan_status: PlanStatusV1) -> None:
    result = transition_approve_action(
        ActionStatusV1.PROPOSED,
        0,
        0,
        effect_type=EffectType.CREATE,
        plan_review_passed=True,
        plan_status=plan_status,
        plan_is_current=True,
        run_status=RunStatusV1.WAITING_APPROVAL,
    )

    assert not result.applied
