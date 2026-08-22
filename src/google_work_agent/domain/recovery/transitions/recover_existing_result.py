"""Known existing-result recovery transition authority."""

from google_work_agent.domain.action.model import ActionCommand
from google_work_agent.domain.enums import ActionStatus, ResultCode
from google_work_agent.domain.results import CommandResult


def transition_recover_existing_result(current_status: ActionStatus, *, current_version: int, expected_version: int) -> CommandResult[ActionStatus, ActionCommand]:
    if expected_version != current_version:
        return CommandResult(False, ResultCode.VERSION_CONFLICT, current_status, current_version, (), "expected_version does not match current_version")
    if current_status is not ActionStatus.UNKNOWN_RESULT:
        return CommandResult(False, ResultCode.STATE_CONFLICT, current_status, current_version, (), "RECOVER_EXISTING_RESULT requires UNKNOWN_RESULT")
    return CommandResult(True, ResultCode.TRANSITION_APPLIED, ActionStatus.EXECUTED, current_version + 1, (ActionCommand.STORE_VERIFICATION,))
