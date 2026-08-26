"""Store completion of a READ Action."""

from google_work_agent.domain.action.model import ActionCommand, ActionStatus, EffectType
from google_work_agent.domain.results import CommandResult, ResultCode


def transition_complete_read_action(
    current_status: ActionStatus,
    current_version: int,
    expected_version: int,
    *,
    effect_type: EffectType,
) -> CommandResult[ActionStatus, ActionCommand]:
    if effect_type is not EffectType.READ or current_status is not ActionStatus.EXECUTING:
        return CommandResult(
            False,
            ResultCode.STATE_CONFLICT,
            current_status,
            current_version,
            (),
            "CompleteReadAction requires READ EXECUTING",
        )
    if expected_version != current_version:
        return CommandResult(
            False,
            ResultCode.VERSION_CONFLICT,
            current_status,
            current_version,
            (),
            "expected_version does not match current_version",
        )
    return CommandResult(
        True, ResultCode.TRANSITION_APPLIED, ActionStatus.EXECUTED, current_version + 1, ()
    )
