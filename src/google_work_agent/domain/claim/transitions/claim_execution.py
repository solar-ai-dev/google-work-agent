"""Canonical Action transition performed by a successful write claim."""

from google_work_agent.domain.action.model import ActionStatusV1, EffectType
from google_work_agent.domain.claim.model import ClaimCommand
from google_work_agent.domain.results import CommandResult, ResultCode


def transition_claim_execution(
    current_status: ActionStatusV1,
    current_version: int,
    expected_version: int,
    *,
    effect_type: EffectType,
) -> CommandResult[ActionStatusV1, ClaimCommand]:
    if effect_type is EffectType.READ:
        return CommandResult(
            False,
            ResultCode.STATE_CONFLICT,
            current_status,
            current_version,
            (),
            "CLAIM_EXECUTION is write-only",
        )
    if current_version < 0 or expected_version < 0:
        raise ValueError("action version must be non-negative")
    if expected_version != current_version:
        return CommandResult(
            False,
            ResultCode.VERSION_CONFLICT,
            current_status,
            current_version,
            (),
            "expected_version does not match current_version",
        )
    if current_status is not ActionStatusV1.APPROVED:
        return CommandResult(
            False,
            ResultCode.STATE_CONFLICT,
            current_status,
            current_version,
            (),
            f"CLAIM_EXECUTION is not allowed from {current_status.value}",
        )
    return CommandResult(
        True, ResultCode.TRANSITION_APPLIED, ActionStatusV1.EXECUTING, current_version + 1, ()
    )
