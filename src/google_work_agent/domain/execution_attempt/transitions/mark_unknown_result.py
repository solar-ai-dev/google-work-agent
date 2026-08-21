"""Uncertain write-result transition authority."""

from google_work_agent.domain.commands import ActionCommand
from google_work_agent.domain.enums import ActionStatus, ResultCode
from google_work_agent.domain.results import CommandResult


def transition_mark_unknown_result(
    current_status: ActionStatus,
    *,
    current_version: int,
    expected_version: int,
) -> CommandResult[ActionStatus, ActionCommand]:
    if expected_version != current_version:
        return CommandResult(False, ResultCode.VERSION_CONFLICT, current_status, current_version, (), "expected_version does not match current_version")
    if current_status is not ActionStatus.EXECUTING:
        return CommandResult(False, ResultCode.STATE_CONFLICT, current_status, current_version, (), "MARK_UNKNOWN_RESULT requires EXECUTING")
    return CommandResult(True, ResultCode.TRANSITION_APPLIED, ActionStatus.UNKNOWN_RESULT, current_version + 1, (ActionCommand.RECOVER_EXISTING_RESULT, ActionCommand.RESOLVE_AS_FAILED))
