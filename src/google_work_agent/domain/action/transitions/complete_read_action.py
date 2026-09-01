"""Store completion of a READ Action."""

from google_work_agent.domain.action.guards.complete_read_action import guard_complete_read_action
from google_work_agent.domain.action.model import ActionCommand, ActionStatusV1, EffectType
from google_work_agent.domain.results import CommandResult, ResultCode


def transition_complete_read_action(
    current_status: ActionStatusV1,
    current_version: int,
    expected_version: int,
    *,
    effect_type: EffectType,
) -> CommandResult[ActionStatusV1, ActionCommand]:
    conflict = guard_complete_read_action(
        current_status, current_version, expected_version, effect_type=effect_type
    )
    if conflict is not None:
        return CommandResult(
            False,
            conflict[0],
            current_status,
            current_version,
            (),
            conflict[1],
        )
    return CommandResult(
        True, ResultCode.TRANSITION_APPLIED, ActionStatusV1.EXECUTED, current_version + 1, ()
    )
