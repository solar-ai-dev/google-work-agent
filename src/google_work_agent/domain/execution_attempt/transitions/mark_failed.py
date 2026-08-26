"""Joint deterministic execution-failure transition authority."""

from google_work_agent.domain.action.model import ActionStatus
from google_work_agent.domain.execution_attempt.model import (
    ExecutionAttemptStatus,
    ExecutionAttemptTransitionDecision,
)
from google_work_agent.domain.results import InvariantViolationError, ResultCode


def transition_mark_failed(
    action_status: ActionStatus,
    *,
    action_version: int,
    expected_action_version: int,
    attempt_status: ExecutionAttemptStatus,
    attempt_version: int,
    expected_attempt_version: int,
    delivery_certainty: str,
) -> ExecutionAttemptTransitionDecision:
    if delivery_certainty != "NOT_SENT":
        raise InvariantViolationError("MarkFailed requires delivery_certainty=NOT_SENT")
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
        action_status is not ActionStatus.EXECUTING
        or attempt_status is not ExecutionAttemptStatus.EXECUTING
    ):
        return ExecutionAttemptTransitionDecision(
            False,
            ResultCode.STATE_CONFLICT,
            action_status,
            action_version,
            attempt_status,
            attempt_version,
            "MarkFailed requires Action EXECUTING and Attempt EXECUTING",
        )
    return ExecutionAttemptTransitionDecision(
        True,
        ResultCode.TRANSITION_APPLIED,
        ActionStatus.FAILED,
        action_version + 1,
        ExecutionAttemptStatus.FAILED,
        attempt_version + 1,
    )
