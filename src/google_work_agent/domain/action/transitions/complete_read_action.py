"""Store completion of a READ Action."""

from google_work_agent.domain.action.model import ActionCommand, ActionStatusV1, EffectType
from google_work_agent.domain.results import CommandResult, ResultCode


def transition_complete_read_action(
    current_status: ActionStatusV1,
    current_version: int,
    expected_version: int,
    *,
    effect_type: EffectType,
) -> CommandResult[ActionStatusV1, ActionCommand]:
    if effect_type is not EffectType.READ or current_status is not ActionStatusV1.EXECUTING:
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
        True, ResultCode.TRANSITION_APPLIED, ActionStatusV1.EXECUTED, current_version + 1, ()
    )
