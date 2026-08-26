"""Joint existing-result recovery transition authority."""

from google_work_agent.domain.action.model import ActionStatus
from google_work_agent.domain.execution_attempt.model import (
    ExecutionAttemptStatus,
    ExecutionAttemptTransitionDecision,
)
from google_work_agent.domain.results import ResultCode


def transition_recover_existing_result(
    action_status: ActionStatus,
    *,
    action_version: int,
    expected_action_version: int,
    attempt_status: ExecutionAttemptStatus,
    attempt_version: int,
    expected_attempt_version: int,
    existing_result_confirmed: bool = True,
) -> ExecutionAttemptTransitionDecision:
    if not existing_result_confirmed:
        return ExecutionAttemptTransitionDecision(
            False,
            ResultCode.STATE_CONFLICT,
            action_status,
            action_version,
            attempt_status,
            attempt_version,
            "RecoverExistingResult requires lookup evidence",
        )
    if action_version != expected_action_version or attempt_version != expected_attempt_version:
        return ExecutionAttemptTransitionDecision(
            False,
            ResultCode.VERSION_CONFLICT,
            action_status,
            action_version,
            attempt_status,
            attempt_version,
            "expected version does not match current version",
        )
    if (
        action_status is not ActionStatus.UNKNOWN_RESULT
        or attempt_status is not ExecutionAttemptStatus.UNKNOWN_RESULT
    ):
        return ExecutionAttemptTransitionDecision(
            False,
            ResultCode.STATE_CONFLICT,
            action_status,
            action_version,
            attempt_status,
            attempt_version,
            "RecoverExistingResult requires Action and Attempt UNKNOWN_RESULT",
        )
    return ExecutionAttemptTransitionDecision(
        True,
        ResultCode.TRANSITION_APPLIED,
        ActionStatus.EXECUTED,
        action_version + 1,
        ExecutionAttemptStatus.SUCCEEDED,
        attempt_version + 1,
    )
