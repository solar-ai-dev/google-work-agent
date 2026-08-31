"""Guard for storing a durable verification outcome."""

from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.verification.model import VerificationStatus


def guard_store_verification(
    current_status: ActionStatusV1,
    *,
    current_version: int,
    expected_version: int,
    verification_status: VerificationStatus,
) -> tuple[ResultCode, str] | None:
    if expected_version != current_version:
        return ResultCode.VERSION_CONFLICT, "expected_version does not match current_version"
    if current_status is not ActionStatusV1.EXECUTED:
        return ResultCode.STATE_CONFLICT, "STORE_VERIFICATION requires EXECUTED"
    if verification_status not in {
        VerificationStatus.VERIFIED,
        VerificationStatus.MISMATCH,
    }:
        raise ValueError("durable verification status must be VERIFIED or MISMATCH")
    return None
