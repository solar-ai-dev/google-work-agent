"""Canonical Action reject transition."""

from google_work_agent.domain.commands import ActionCommand
from google_work_agent.domain.enums import ActionStatus, EffectType, ResultCode
from google_work_agent.domain.results import CommandResult

_WRITE_ALLOWED = frozenset({ActionStatus.PROPOSED, ActionStatus.MODIFIED, ActionStatus.APPROVED})
_READ_ALLOWED = frozenset({ActionStatus.PROPOSED, ActionStatus.MODIFIED})


def transition_reject_action(current_status: ActionStatus, current_version: int, expected_version: int, *, effect_type: EffectType) -> CommandResult[ActionStatus, ActionCommand]:
    if current_version < 0 or expected_version < 0:
        raise ValueError("action version must be non-negative")
    if expected_version != current_version:
        return CommandResult(False, ResultCode.VERSION_CONFLICT, current_status, current_version, (), "expected_version does not match current_version")
    allowed = _READ_ALLOWED if effect_type is EffectType.READ else _WRITE_ALLOWED
    if current_status not in allowed:
        return CommandResult(False, ResultCode.STATE_CONFLICT, current_status, current_version, (), f"REJECT_ACTION is not allowed from {current_status.value}")
    return CommandResult(True, ResultCode.TRANSITION_APPLIED, ActionStatus.REJECTED, current_version + 1, ())
