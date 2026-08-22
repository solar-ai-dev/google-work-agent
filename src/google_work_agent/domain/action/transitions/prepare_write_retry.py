"""Canonical FAILED write Action retry preparation transition."""

from google_work_agent.domain.action.model import ActionCommand
from google_work_agent.domain.enums import ActionStatus, EffectType, ResultCode
from google_work_agent.domain.results import CommandResult


def transition_prepare_write_retry(current_status: ActionStatus, current_version: int, expected_version: int, *, effect_type: EffectType) -> CommandResult[ActionStatus, ActionCommand]:
    if effect_type is EffectType.READ:
        return CommandResult(False, ResultCode.STATE_CONFLICT, current_status, current_version, (), "PREPARE_WRITE_RETRY is write-only")
    if current_version < 0 or expected_version < 0:
        raise ValueError("action version must be non-negative")
    if expected_version != current_version:
        return CommandResult(False, ResultCode.VERSION_CONFLICT, current_status, current_version, (), "expected_version does not match current_version")
    if current_status is not ActionStatus.FAILED:
        return CommandResult(False, ResultCode.STATE_CONFLICT, current_status, current_version, (), f"PREPARE_WRITE_RETRY is not allowed from {current_status.value}")
    return CommandResult(True, ResultCode.TRANSITION_APPLIED, ActionStatus.MODIFIED, current_version + 1, ())
