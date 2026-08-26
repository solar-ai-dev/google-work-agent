"""Definitively settle an unknown execution result as not sent."""

from google_work_agent.domain.action.model import ActionCommand
from google_work_agent.domain.enums import ActionStatus, ResultCode
from google_work_agent.domain.exceptions import InvariantViolationError
from google_work_agent.domain.results import CommandResult


def transition_resolve_as_failed(
    current_status: ActionStatus,
    *,
    current_version: int,
    expected_version: int,
    result_not_executed_confirmed: bool,
) -> CommandResult[ActionStatus, ActionCommand]:
    if not result_not_executed_confirmed:
        raise InvariantViolationError("RESOLVE_AS_FAILED requires confirmed non-execution")
    if expected_version != current_version:
        return CommandResult(
            False,
            ResultCode.VERSION_CONFLICT,
            current_status,
            current_version,
            (),
            "expected_version does not match current_version",
        )
    if current_status is not ActionStatus.UNKNOWN_RESULT:
        return CommandResult(
            False,
            ResultCode.STATE_CONFLICT,
            current_status,
            current_version,
            (),
            "RESOLVE_AS_FAILED requires UNKNOWN_RESULT",
        )
    return CommandResult(
        True,
        ResultCode.TRANSITION_APPLIED,
        ActionStatus.FAILED,
        current_version + 1,
        (ActionCommand.PREPARE_WRITE_RETRY,),
    )
