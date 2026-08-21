"""Application boundary for FAILED write retry preparation."""

from dataclasses import dataclass

from google_work_agent.domain.action.transitions.prepare_write_retry import transition_prepare_write_retry
from google_work_agent.domain.commands import ActionCommand
from google_work_agent.domain.enums import ActionStatus, EffectType, ResultCode


@dataclass(frozen=True, slots=True)
class PrepareWriteRetryCommand:
    current_status: ActionStatus
    current_version: int
    expected_version: int
    effect_type: EffectType


@dataclass(frozen=True, slots=True)
class PrepareWriteRetryResult:
    applied: bool
    result_code: ResultCode
    current_status: ActionStatus
    current_version: int
    next_allowed_commands: tuple[ActionCommand, ...]
    conflict_detail: str | None = None


class PrepareWriteRetryHandler:
    def __call__(self, command: PrepareWriteRetryCommand) -> PrepareWriteRetryResult:
        result = transition_prepare_write_retry(
            command.current_status,
            command.current_version,
            command.expected_version,
            effect_type=command.effect_type,
        )
        return PrepareWriteRetryResult(
            applied=result.applied,
            result_code=result.result_code,
            current_status=result.current_status,
            current_version=result.current_version,
            next_allowed_commands=result.next_allowed_commands,
            conflict_detail=result.conflict_detail,
        )
