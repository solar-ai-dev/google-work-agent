"""Canonical Action reject transition."""

from google_work_agent.domain.action.guards.reject_action import guard_reject_action
from google_work_agent.domain.action.model import ActionCommand, ActionStatusV1, EffectType
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.results import CommandResult, ResultCode


def transition_reject_action(
    current_status: ActionStatusV1,
    current_version: int,
    expected_version: int,
    *,
    effect_type: EffectType,
    plan_status: PlanStatusV1,
    plan_is_current: bool,
) -> CommandResult[ActionStatusV1, ActionCommand]:
    conflict = guard_reject_action(
        current_status,
        current_version,
        expected_version,
        effect_type=effect_type,
        plan_status=plan_status,
        plan_is_current=plan_is_current,
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
        True, ResultCode.TRANSITION_APPLIED, ActionStatusV1.REJECTED, current_version + 1, ()
    )
