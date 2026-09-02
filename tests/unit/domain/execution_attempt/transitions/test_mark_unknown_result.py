from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.execution_attempt.transitions.mark_unknown_result import (
    transition_mark_unknown_result,
)


def test_mark_unknown__result_does_not__offer_direct_retry() -> None:
    result = transition_mark_unknown_result(
        ActionStatusV1.EXECUTING,
        action_version=0,
        expected_action_version=0,
        attempt_status=ExecutionAttemptStatusV1.EXECUTING,
        attempt_version=0,
        expected_attempt_version=0,
    )

    assert result.current_status is ActionStatusV1.UNKNOWN_RESULT
    assert result.attempt_status is ExecutionAttemptStatusV1.UNKNOWN_RESULT
