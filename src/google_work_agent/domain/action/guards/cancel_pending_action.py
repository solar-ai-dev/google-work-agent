"""Guard for cancelling a pending Action."""

from google_work_agent.domain.action.guards.current_plan_authority import (
    guard_current_plan_authority,
)
from google_work_agent.domain.action.model import ActionStatusV1, EffectType
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.results import ResultCode

_ALLOWED = frozenset(
    {
        ActionStatusV1.PROPOSED,
        ActionStatusV1.MODIFIED,
        ActionStatusV1.APPROVED,
        ActionStatusV1.EXPIRED,
    }
)
_WRITE_PLAN_STATUSES = frozenset({PlanStatusV1.WAITING_APPROVAL})
_READ_PLAN_STATUSES = frozenset({PlanStatusV1.ACTIVE})


def guard_cancel_pending_action(
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
        allowed_statuses=(
            _READ_PLAN_STATUSES if effect_type is EffectType.READ else _WRITE_PLAN_STATUSES
        ),
    )
    if authority_conflict is not None:
        return ResultCode.STATE_CONFLICT, authority_conflict
    if current_version < 0 or expected_version < 0:
        raise ValueError("action version must be non-negative")
    if expected_version != current_version:
        return ResultCode.VERSION_CONFLICT, "expected_version does not match current_version"
    if current_status not in _ALLOWED:
        return (
            ResultCode.STATE_CONFLICT,
            f"CANCEL_PENDING_ACTION is not allowed from {current_status.value}",
        )
    return None
