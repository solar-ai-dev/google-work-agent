"""Guard for recovering a confirmed existing write result."""

from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.results import ResultCode


def guard_recover_existing_result(
    action_status: ActionStatusV1,
    *,
    action_version: int,
    expected_action_version: int,
    attempt_status: ExecutionAttemptStatusV1,
    attempt_version: int,
    expected_attempt_version: int,
    existing_result_confirmed: bool,
) -> tuple[ResultCode, str] | None:
    if not existing_result_confirmed:
        return ResultCode.STATE_CONFLICT, "RecoverExistingResult requires lookup evidence"
    if action_version != expected_action_version or attempt_version != expected_attempt_version:
        return ResultCode.VERSION_CONFLICT, "expected version does not match current version"
    if (
        action_status is not ActionStatusV1.UNKNOWN_RESULT
        or attempt_status is not ExecutionAttemptStatusV1.UNKNOWN_RESULT
    ):
        return (
            ResultCode.STATE_CONFLICT,
            "RecoverExistingResult requires Action and Attempt UNKNOWN_RESULT",
        )
    return None
