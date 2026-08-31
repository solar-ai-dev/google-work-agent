"""Joint deterministic non-execution settlement authority."""

from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.execution_attempt.guards.resolve_as_failed import (
    guard_resolve_as_failed,
)
from google_work_agent.domain.execution_attempt.model import (
    ExecutionAttemptStatusV1,
    ExecutionAttemptTransitionDecision,
)
from google_work_agent.domain.results import ResultCode


def transition_resolve_as_failed(
    action_status: ActionStatusV1,
    *,
    action_version: int,
    expected_action_version: int,
    attempt_status: ExecutionAttemptStatusV1,
    attempt_version: int,
    expected_attempt_version: int,
    result_not_executed_confirmed: bool,
) -> ExecutionAttemptTransitionDecision:
    conflict = guard_resolve_as_failed(
        action_status,
        action_version=action_version,
        expected_action_version=expected_action_version,
        attempt_status=attempt_status,
        attempt_version=attempt_version,
        expected_attempt_version=expected_attempt_version,
        result_not_executed_confirmed=result_not_executed_confirmed,
    )
    if conflict is not None:
        return ExecutionAttemptTransitionDecision(
            False,
            conflict[0],
            action_status,
            action_version,
            attempt_status,
            attempt_version,
            conflict[1],
        )
    return ExecutionAttemptTransitionDecision(
        True,
        ResultCode.TRANSITION_APPLIED,
        ActionStatusV1.FAILED,
        action_version + 1,
        ExecutionAttemptStatusV1.FAILED,
        attempt_version + 1,
    )
