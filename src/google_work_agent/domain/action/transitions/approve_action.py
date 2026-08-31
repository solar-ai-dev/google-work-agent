"""Approve a write Action after a current Plan review passes."""

from google_work_agent.domain.action.guards.approve_action import guard_approve_action
from google_work_agent.domain.action.model import ActionCommand, ActionStatusV1, EffectType
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.results import CommandResult, ResultCode
from google_work_agent.domain.run.model import RunStatusV1


def transition_approve_action(
    current_status: ActionStatusV1,
    current_version: int,
    expected_version: int,
    *,
    effect_type: EffectType,
    plan_review_passed: bool,
    plan_status: PlanStatusV1,
    plan_is_current: bool,
    run_status: RunStatusV1,
) -> CommandResult[ActionStatusV1, ActionCommand]:
    conflict = guard_approve_action(
        current_status,
        current_version,
        expected_version,
        effect_type=effect_type,
        plan_review_passed=plan_review_passed,
        plan_status=plan_status,
        plan_is_current=plan_is_current,
        run_status=run_status,
    )
    if conflict is not None:
        return CommandResult(
            False,
            conflict[0],
            current_status,
            current_version,
            (),
            conflict[1],
        )
    return CommandResult(
        True, ResultCode.TRANSITION_APPLIED, ActionStatusV1.APPROVED, current_version + 1, ()
    )
