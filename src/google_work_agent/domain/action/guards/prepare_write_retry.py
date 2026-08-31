"""Guard for preparing a failed write Action retry."""

from google_work_agent.domain.action.guards.current_plan_authority import (
    guard_current_plan_authority,
)
from google_work_agent.domain.action.model import ActionStatusV1, EffectType
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.results import ResultCode

_ALLOWED_PLAN_STATUSES = frozenset({PlanStatusV1.WAITING_APPROVAL})


def guard_prepare_write_retry(
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
    if effect_type is EffectType.READ:
        return ResultCode.STATE_CONFLICT, "PREPARE_WRITE_RETRY is write-only"
    if current_version < 0 or expected_version < 0:
        raise ValueError("action version must be non-negative")
    if expected_version != current_version:
        return ResultCode.VERSION_CONFLICT, "expected_version does not match current_version"
    if current_status is not ActionStatusV1.FAILED:
        return (
            ResultCode.STATE_CONFLICT,
            f"PREPARE_WRITE_RETRY is not allowed from {current_status.value}",
        )
    return None
