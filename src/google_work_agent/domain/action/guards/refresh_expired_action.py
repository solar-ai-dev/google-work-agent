"""Guard for refreshing an expired write Action."""

from google_work_agent.domain.action.guards.current_plan_authority import (
    guard_current_plan_authority,
)
from google_work_agent.domain.action.model import ActionStatusV1, EffectType
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.results import ResultCode

_ALLOWED_PLAN_STATUSES = frozenset({PlanStatusV1.WAITING_APPROVAL})


def guard_refresh_expired_action(
    current_status: ActionStatusV1,
    current_version: int,
    expected_version: int,
    *,
    effect_type: EffectType,
    plan_status: PlanStatusV1,
    plan_is_current: bool,
) -> tuple[ResultCode, str] | None:
    authority_conflict = guard_current_plan_authority(
        plan_status=plan_status,
        plan_is_current=plan_is_current,
        allowed_statuses=_ALLOWED_PLAN_STATUSES,
    )
    if authority_conflict is not None:
        return ResultCode.STATE_CONFLICT, authority_conflict
    if effect_type is EffectType.READ or current_status is not ActionStatusV1.EXPIRED:
        return ResultCode.STATE_CONFLICT, "RefreshExpiredAction requires an expired WRITE Action"
    if expected_version != current_version:
        return ResultCode.VERSION_CONFLICT, "expected_version does not match current_version"
    return None
