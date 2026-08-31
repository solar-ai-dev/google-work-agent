"""Verification outcome transition authority."""

from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.results import CommandResult, ResultCode
from google_work_agent.domain.verification.guards.store_verification import (
    guard_store_verification,
)
from google_work_agent.domain.verification.model import VerificationCommand, VerificationStatus


def transition_store_verification(
    current_status: ActionStatusV1,
    *,
    current_version: int,
    expected_version: int,
    verification_status: VerificationStatus,
) -> CommandResult[ActionStatusV1, VerificationCommand]:
    conflict = guard_store_verification(
        current_status,
        current_version=current_version,
        expected_version=expected_version,
        verification_status=verification_status,
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
    target = (
        ActionStatusV1.VERIFIED
        if verification_status is VerificationStatus.VERIFIED
        else ActionStatusV1.MISMATCH
    )
    return CommandResult(True, ResultCode.TRANSITION_APPLIED, target, current_version + 1, ())
