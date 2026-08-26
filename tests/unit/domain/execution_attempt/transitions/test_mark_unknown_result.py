from google_work_agent.domain.action.model import ActionStatus
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatus
from google_work_agent.domain.execution_attempt.transitions.mark_unknown_result import (
    transition_mark_unknown_result,
)


def test_mark_unknown_result_does_not_offer_direct_retry() -> None:
    result = transition_mark_unknown_result(
        ActionStatus.EXECUTING,
        action_version=0,
        expected_action_version=0,
        attempt_status=ExecutionAttemptStatus.EXECUTING,
        attempt_version=0,
        expected_attempt_version=0,
    )

    assert result.current_status is ActionStatus.UNKNOWN_RESULT
    assert result.attempt_status is ExecutionAttemptStatus.UNKNOWN_RESULT
