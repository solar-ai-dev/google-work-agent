"""Verification outcome transition authority."""

from google_work_agent.domain.action.model import ActionStatus
from google_work_agent.domain.results import CommandResult, ResultCode
from google_work_agent.domain.verification.model import VerificationCommand, VerificationStatus


def transition_store_verification(
    current_status: ActionStatus,
    *,
    current_version: int,
    expected_version: int,
    verification_status: VerificationStatus,
) -> CommandResult[ActionStatus, VerificationCommand]:
    if expected_version != current_version:
        return CommandResult(
            False,
            ResultCode.VERSION_CONFLICT,
            current_status,
            current_version,
            (),
            "expected_version does not match current_version",
        )
    if current_status is not ActionStatus.EXECUTED:
        return CommandResult(
            False,
            ResultCode.STATE_CONFLICT,
            current_status,
            current_version,
            (),
            "STORE_VERIFICATION requires EXECUTED",
        )
    if verification_status not in {
        VerificationStatus.VERIFIED,
        VerificationStatus.MISMATCH,
    }:
        raise ValueError("durable verification status must be VERIFIED or MISMATCH")
    target = (
        ActionStatus.VERIFIED
        if verification_status is VerificationStatus.VERIFIED
        else ActionStatus.MISMATCH
    )
    return CommandResult(True, ResultCode.TRANSITION_APPLIED, target, current_version + 1, ())
