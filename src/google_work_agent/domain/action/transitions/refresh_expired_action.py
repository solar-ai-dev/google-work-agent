"""Refresh an expired Action before a new review and Approval."""

from google_work_agent.domain.action.guards.current_plan_authority import (
    guard_current_plan_authority,
)
from google_work_agent.domain.action.model import ActionCommand, ActionStatusV1, EffectType
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.results import CommandResult, ResultCode

_ALLOWED_PLAN_STATUSES = frozenset({PlanStatusV1.WAITING_APPROVAL})


def transition_refresh_expired_action(
    current_status: ActionStatusV1,
    current_version: int,
    expected_version: int,
    *,
    effect_type: EffectType,
    plan_status: PlanStatusV1,
    plan_is_current: bool,
) -> CommandResult[ActionStatusV1, ActionCommand]:
    authority_conflict = guard_current_plan_authority(
        plan_status=plan_status,
        plan_is_current=plan_is_current,
        allowed_statuses=_ALLOWED_PLAN_STATUSES,
    )
    if authority_conflict is not None:
        return CommandResult(
            False,
            ResultCode.STATE_CONFLICT,
            current_status,
            current_version,
            (),
            authority_conflict,
        )
    if effect_type is EffectType.READ or current_status is not ActionStatusV1.EXPIRED:
        return CommandResult(
            False,
            ResultCode.STATE_CONFLICT,
            current_status,
            current_version,
            (),
            "RefreshExpiredAction requires an expired WRITE Action",
        )
    if expected_version != current_version:
        return CommandResult(
            False,
            ResultCode.VERSION_CONFLICT,
            current_status,
            current_version,
            (),
            "expected_version does not match current_version",
        )
    return CommandResult(
        True, ResultCode.TRANSITION_APPLIED, ActionStatusV1.MODIFIED, current_version + 1, ()
    )
