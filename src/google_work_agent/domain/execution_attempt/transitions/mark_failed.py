"""Definitive execution failure transition authority."""

from google_work_agent.domain.action.model import ActionCommand
from google_work_agent.domain.enums import ActionStatus, ResultCode
from google_work_agent.domain.exceptions import InvariantViolationError
from google_work_agent.domain.results import CommandResult


def transition_mark_failed(
    current_status: ActionStatus,
    *,
    current_version: int,
    expected_version: int,
    delivery_certainty: str,
) -> CommandResult[ActionStatus, ActionCommand]:
    if delivery_certainty != "NOT_SENT":
        raise InvariantViolationError("MARK_FAILED requires delivery_certainty=NOT_SENT")
    if expected_version != current_version:
        return CommandResult(False, ResultCode.VERSION_CONFLICT, current_status, current_version, (), "expected_version does not match current_version")
    if current_status is not ActionStatus.EXECUTING:
        return CommandResult(False, ResultCode.STATE_CONFLICT, current_status, current_version, (), "MARK_FAILED requires EXECUTING")
    return CommandResult(True, ResultCode.TRANSITION_APPLIED, ActionStatus.FAILED, current_version + 1, (ActionCommand.PREPARE_WRITE_RETRY,))
