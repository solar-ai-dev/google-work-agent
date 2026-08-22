"""Pure Domain transition for resuming a confirmed LangGraph interrupt."""

from google_work_agent.domain.run.model import RunCommand
from google_work_agent.domain.enums import ResultCode, RunStatus
from google_work_agent.domain.exceptions import InvariantViolationError
from google_work_agent.domain.results import CommandResult
from google_work_agent.domain.run.transitions.run import next_allowed_run_commands

_CONFIRMATION_RESUME_STATUSES = frozenset(
    {
        RunStatus.ANALYZING,
        RunStatus.RETRIEVING,
        RunStatus.PLANNING,
    }
)


def resume_confirmation(
    current_status: RunStatus,
    *,
    current_version: int,
    expected_version: int,
    resume_status: RunStatus,
) -> CommandResult[RunStatus, RunCommand]:
    """Restore the safe pre-confirmation Domain phase after a valid response.

    The LangGraph checkpoint owns the exact owner-subgraph/node resume target;
    this Domain transition restores only the coarse Run status that existed
    before ``RequestConfirmation``. It never chooses a graph node.
    """
    if current_version < 0 or expected_version < 0:
        raise InvariantViolationError("run versions must be non-negative")
    if resume_status not in _CONFIRMATION_RESUME_STATUSES:
        raise InvariantViolationError(
            "confirmation resume status must be ANALYZING, RETRIEVING, or PLANNING"
        )
    if expected_version != current_version:
        return CommandResult(
            applied=False,
            result_code=ResultCode.VERSION_CONFLICT,
            current_status=current_status,
            current_version=current_version,
            next_allowed_commands=(RunCommand.RESUME_CONFIRMATION,),
            conflict_detail="expected_version does not match current_version",
        )
    if current_status is not RunStatus.WAITING_CONFIRMATION:
        return CommandResult(
            applied=False,
            result_code=ResultCode.STATE_CONFLICT,
            current_status=current_status,
            current_version=current_version,
            next_allowed_commands=next_allowed_run_commands(current_status),
            conflict_detail=(
                "RESUME_CONFIRMATION is only allowed from WAITING_CONFIRMATION"
            ),
        )
    return CommandResult(
        applied=True,
        result_code=ResultCode.TRANSITION_APPLIED,
        current_status=resume_status,
        current_version=current_version + 1,
        next_allowed_commands=next_allowed_run_commands(resume_status),
        conflict_detail=None,
    )
