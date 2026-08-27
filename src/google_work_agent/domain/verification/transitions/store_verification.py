"""Verification outcome transition authority."""

from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.results import CommandResult, ResultCode
from google_work_agent.domain.verification.model import VerificationCommand, VerificationStatus


def transition_store_verification(
    current_status: ActionStatusV1,
    *,
    current_version: int,
    expected_version: int,
    verification_status: VerificationStatus,
) -> CommandResult[ActionStatusV1, VerificationCommand]:
    if expected_version != current_version:
        return CommandResult(
            False,
            ResultCode.VERSION_CONFLICT,
            current_status,
            current_version,
            (),
            "expected_version does not match current_version",
        )
    if current_status is not ActionStatusV1.EXECUTED:
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
        ActionStatusV1.VERIFIED
        if verification_status is VerificationStatus.VERIFIED
        else ActionStatusV1.MISMATCH
    )
    return CommandResult(True, ResultCode.TRANSITION_APPLIED, target, current_version + 1, ())
