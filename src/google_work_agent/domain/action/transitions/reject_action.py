"""Canonical Action reject transition."""

from google_work_agent.domain.action.guards.current_plan_authority import (
    guard_current_plan_authority,
)
from google_work_agent.domain.action.model import ActionCommand, ActionStatus, EffectType
from google_work_agent.domain.plan.model import PlanStatus
from google_work_agent.domain.results import CommandResult, ResultCode

_WRITE_ALLOWED = frozenset({ActionStatus.PROPOSED, ActionStatus.MODIFIED, ActionStatus.APPROVED})
_READ_ALLOWED = frozenset({ActionStatus.PROPOSED, ActionStatus.MODIFIED})


def transition_reject_action(
    current_status: ActionStatus,
    current_version: int,
    expected_version: int,
    *,
    effect_type: EffectType,
    plan_status: PlanStatus,
    plan_is_current: bool,
) -> CommandResult[ActionStatus, ActionCommand]:
    authority_conflict = guard_current_plan_authority(
        plan_status=plan_status, plan_is_current=plan_is_current
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
    if current_version < 0 or expected_version < 0:
        raise ValueError("action version must be non-negative")
    if expected_version != current_version:
        return CommandResult(
            False,
            ResultCode.VERSION_CONFLICT,
            current_status,
            current_version,
            (),
            "expected_version does not match current_version",
        )
    allowed = _READ_ALLOWED if effect_type is EffectType.READ else _WRITE_ALLOWED
    if current_status not in allowed:
        return CommandResult(
            False,
            ResultCode.STATE_CONFLICT,
            current_status,
            current_version,
            (),
            f"REJECT_ACTION is not allowed from {current_status.value}",
        )
    return CommandResult(
        True, ResultCode.TRANSITION_APPLIED, ActionStatus.REJECTED, current_version + 1, ()
    )
