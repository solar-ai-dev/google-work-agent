"""Prepare a definitive failed write for a new approval cycle."""

from google_work_agent.domain.action.model import ActionCommand
from google_work_agent.domain.enums import ActionStatus, ResultCode
from google_work_agent.domain.results import CommandResult


def transition_prepare_write_retry(current_status: ActionStatus, *, current_version: int, expected_version: int) -> CommandResult[ActionStatus, ActionCommand]:
    if expected_version != current_version:
        return CommandResult(False, ResultCode.VERSION_CONFLICT, current_status, current_version, (), "expected_version does not match current_version")
    if current_status is not ActionStatus.FAILED:
        return CommandResult(False, ResultCode.STATE_CONFLICT, current_status, current_version, (), "PREPARE_WRITE_RETRY requires FAILED")
    return CommandResult(True, ResultCode.TRANSITION_APPLIED, ActionStatus.MODIFIED, current_version + 1, (ActionCommand.MODIFY_ACTION, ActionCommand.APPROVE_ACTION))
