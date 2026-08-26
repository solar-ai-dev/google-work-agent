"""Joint deterministic non-execution settlement authority."""

from google_work_agent.domain.action.model import ActionStatus
from google_work_agent.domain.execution_attempt.model import (
    ExecutionAttemptStatus,
    ExecutionAttemptTransitionDecision,
)
from google_work_agent.domain.results import InvariantViolationError, ResultCode


def transition_resolve_as_failed(
    action_status: ActionStatus,
    *,
    action_version: int,
    expected_action_version: int,
    attempt_status: ExecutionAttemptStatus,
    attempt_version: int,
    expected_attempt_version: int,
    result_not_executed_confirmed: bool,
) -> ExecutionAttemptTransitionDecision:
    if not result_not_executed_confirmed:
        raise InvariantViolationError("ResolveAsFailed requires confirmed non-execution")
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
            "ResolveAsFailed requires Action and Attempt UNKNOWN_RESULT",
        )
    return ExecutionAttemptTransitionDecision(
        True,
        ResultCode.TRANSITION_APPLIED,
        ActionStatus.FAILED,
        action_version + 1,
        ExecutionAttemptStatus.FAILED,
        attempt_version + 1,
    )
