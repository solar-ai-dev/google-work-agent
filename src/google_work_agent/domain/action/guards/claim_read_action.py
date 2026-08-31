"""Guard for claiming a READ Action."""

from google_work_agent.domain.action.model import ActionStatusV1, EffectType
from google_work_agent.domain.results import ResultCode


def guard_claim_read_action(
    current_status: ActionStatusV1,
    current_version: int,
    expected_version: int,
    *,
    effect_type: EffectType,
) -> tuple[ResultCode, str] | None:
    if effect_type is not EffectType.READ:
        return ResultCode.STATE_CONFLICT, "ClaimReadAction is READ-only"
    if expected_version != current_version:
        return ResultCode.VERSION_CONFLICT, "expected_version does not match current_version"
    if current_status is not ActionStatusV1.PROPOSED:
        return ResultCode.STATE_CONFLICT, "ClaimReadAction requires PROPOSED"
    return None
