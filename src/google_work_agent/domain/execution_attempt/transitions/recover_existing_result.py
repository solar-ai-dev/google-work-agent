"""Joint existing-result recovery transition authority."""

from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.execution_attempt.guards.recover_existing_result import (
    guard_recover_existing_result,
)
from google_work_agent.domain.execution_attempt.model import (
    ExecutionAttemptStatusV1,
    ExecutionAttemptTransitionDecision,
)
from google_work_agent.domain.results import ResultCode


def transition_recover_existing_result(
    action_status: ActionStatusV1,
    *,
    action_version: int,
    expected_action_version: int,
    attempt_status: ExecutionAttemptStatusV1,
    attempt_version: int,
    expected_attempt_version: int,
    existing_result_confirmed: bool = True,
) -> ExecutionAttemptTransitionDecision:
    conflict = guard_recover_existing_result(
        action_status,
        action_version=action_version,
        expected_action_version=expected_action_version,
        attempt_status=attempt_status,
        attempt_version=attempt_version,
        expected_attempt_version=expected_attempt_version,
        existing_result_confirmed=existing_result_confirmed,
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
        ActionStatusV1.EXECUTED,
        action_version + 1,
        ExecutionAttemptStatusV1.SUCCEEDED,
        attempt_version + 1,
    )
