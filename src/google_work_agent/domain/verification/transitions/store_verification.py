"""Verification outcome transition authority."""

from google_work_agent.domain.action.model import ActionCommand
from google_work_agent.domain.enums import ActionStatus, ResultCode, VerificationStatus
from google_work_agent.domain.results import CommandResult


def transition_store_verification(
    current_status: ActionStatus,
    *,
    current_version: int,
    expected_version: int,
    verification_status: VerificationStatus,
) -> CommandResult[ActionStatus, ActionCommand]:
    if expected_version != current_version:
        return CommandResult(False, ResultCode.VERSION_CONFLICT, current_status, current_version, (), "expected_version does not match current_version")
    if current_status is not ActionStatus.EXECUTED:
        return CommandResult(False, ResultCode.STATE_CONFLICT, current_status, current_version, (), "STORE_VERIFICATION requires EXECUTED")
    target = ActionStatus.VERIFIED if verification_status is VerificationStatus.VERIFIED else ActionStatus.MISMATCH
    return CommandResult(True, ResultCode.TRANSITION_APPLIED, target, current_version + 1, ())
